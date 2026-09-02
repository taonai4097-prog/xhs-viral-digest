#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
品牌风格锁 + 生图提示词模板引擎（pipeline/image_prompt.py）

企业级依据（研究结论，见 research/ 与 docs/生图配置指南.md）：
  1. 风格一致性靠「固定 style block 反复复用」保证，不靠模型自觉
     —— 所以品牌规范必须固化成常量，每次生成原样拼接。
  2. 文字不靠生图模型渲染（中文必乱码），AI 只出「无文字底图」
     —— 所以提示词强制含「无文字/无水印」，标题由后期压字完成。
  3. 固定字眼要「系统锁死」而不是靠人记得写
     —— 所以有 REQUIRED_TOKENS + validate_prompt() 质量门禁。

账号即一等公民（P0）：品牌锁绑定 accounts/<id>/brand.json，绝不写死具体账号。
  - brand_block / build_operator_card / build_image_prompt 的 brand 维度由
    account（账号 ID）或 brand_profile（原始 dict）提供，二选一。
  - 不指定 account 且没给 brand_profile -> 抛 AccountError（fail-fast，防串味）。

对外接口：
  build_image_prompt(subject, role, account, platform) -> 完整提示词
  ensure_prompt(agent_prompt, ...)                  -> 已合规则原样返回，否则包装
  validate_prompt(prompt)                           -> (ok, missing_tokens)
  build_operator_card(data, account, platform)       -> 给运营的提示词卡片(markdown)
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import accounts as _accts

# ---------------------------------------------------------------- 平台规格
PLATFORM_SPECS = {
    "小红书": {"ratio": "3:4 竖版", "size": "1080x1440"},
    "抖音": {"ratio": "9:16 竖版", "size": "1080x1920"},
}
DEFAULT_PLATFORM = "小红书"

# ---------------------------------------------------------------- 强制固定字眼
# 用户要求「强制加固定提示词字眼」：每次生成必须带上，并在 validate_prompt 里卡关。
# 两种模式共享「基础后缀」，文字约束按 allow_text 切换（V6 allow_text 开关）：
#   allow_text=False（默认）-> 出无文字底图（所有模型通用、最稳），标题后期用设计工具压；
#   allow_text=True         -> 允许模型在画面压大标题（豆包等中文渲染尚可，省去后期压字），
#                              仍禁水印/二维码/小字堆砌。
BASE_SUFFIX = "风格统一, 高清细节, 与同篇其他图同色板同滤镜"
SUFFIX_NO_TEXT = BASE_SUFFIX + ", 无文字, 无水印"
SUFFIX_WITH_TEXT = BASE_SUFFIX + ", 无水印, 无二维码, 不堆砌小字, 标题大字清晰可读"

# 门禁基础必含（两种模式共用）
REQUIRED_BASE = ["风格统一", "无水印"]
# 兼容旧引用：默认（无文字）模式必含字眼 = 基础 + 无文字
REQUIRED_TOKENS = REQUIRED_BASE + ["无文字"]
FIXED_SUFFIX = SUFFIX_NO_TEXT

# 品牌锁冲突词（V5 红队 P2-1 + 2026-09-02 补中文深色表述）：
# 主体描述若自带这些词，会覆盖品牌色板 → 四图四色。生成时自动剥离并告警，
# 确保「同色板」铁律不被主体描述破坏。
STYLE_CONFLICT_TOKENS = [
    "dark", "dramatic", "high contrast", "neon",
    "深黑", "暗黑", "高对比", "高反差", "霓虹", "冷艳",
    "深色背景", "黑底", "暗色背景", "黑色背景", "dark background",
]

# 文案风格锁/视觉负向的兜底默认值（防 KeyError）
NEG_DEFAULT = "无文字、无水印、不堆砌元素"


def detect_style_conflict(text):
    """检测主体/提示词里与品牌锁冲突的色调词。返回命中词列表。"""
    t = (text or "").lower()
    return [tok for tok in STYLE_CONFLICT_TOKENS if tok.lower() in t]


def strip_conflict(text):
    """剥离冲突色调词，返回 (清洗后文本, 被剥离词列表)。"""
    if not text:
        return text, []
    hits = detect_style_conflict(text)
    if not hits:
        return text, []
    clean = text
    for tok in hits:
        clean = re.sub(r"\s*" + re.escape(tok) + r"\s*", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s{2,}", " ", clean).strip()
    return clean, hits


def _resolve_brand_dict(account=None, brand_profile=None):
    """account（加载 brand.json）优先；否则用直接给的 brand_profile dict。"""
    if isinstance(brand_profile, dict) and brand_profile:
        return brand_profile
    if account:
        return _accts.load_brand(account)
    return None


def brand_block(account=None, brand_profile=None, allow_text=False):
    """把品牌视觉规范压成一段固定的 style block（每次生成原样拼接，保证一致）。

    account / brand_profile 二选一；都没有 -> AccountError（fail-fast）。
    兼容两种 schema：新 brand.json 视觉在 visual 子块；旧/测试可平铺在顶层。
    allow_text=True 时会剔除负向约束里的「无文字」—— 否则提示词一边允许压标题、
    一边要求无文字，自相矛盾（品牌锁默认 negative 均含「无文字」）。
    """
    b = _resolve_brand_dict(account, brand_profile)
    if not b:
        raise _accts.AccountError(
            "brand_block 需要 account 或 brand_profile（账号品牌锁缺失）。"
        )
    v = b.get("visual", b) or {}
    neg = str(v.get("negative", NEG_DEFAULT) or NEG_DEFAULT)
    if allow_text:
        neg = re.sub(r"无文字\s*[、,，]?\s*", "", neg).strip("、,， ")
    return (
        f"配色：{v.get('palette', '（未分析）')}；"
        f"风格：{v.get('style', '（未分析）')}；"
        f"光照：{v.get('lighting', '（未分析）')}；"
        f"构图：{v.get('composition', '（未分析）')}；"
        f"负向约束：{neg or '无水印、不堆砌元素'}"
    )


def build_image_prompt(subject, role="封面", account=None, brand_profile=None,
                       platform=None, extra="", allow_text=False):
    """
    拼接完整提示词 = 平台规格 + 品牌风格锁 + 画面主体 + 强制后缀。
    subject：只写「画面里有什么」，不要写风格（风格由品牌锁统一管）。
    allow_text=False（默认）：出无文字底图，标题后期压。
    allow_text=True：允许模型压大标题（豆包等中文渲染尚可的模型用），仍禁水印/二维码。
    """
    platform = platform or os.environ.get("IMAGE_PLATFORM") or DEFAULT_PLATFORM
    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS[DEFAULT_PLATFORM])
    parts = [
        f"{platform}{role}，{spec['ratio']}，{spec['size']}",
        brand_block(account=account, brand_profile=brand_profile, allow_text=allow_text),
        f"画面主体：{subject}",
    ]
    if extra:
        parts.append(str(extra).strip())
    parts.append(SUFFIX_WITH_TEXT if allow_text else SUFFIX_NO_TEXT)
    return "；".join(parts)


def validate_prompt(prompt, allow_text=False):
    """
    质量门禁（自适应两种模式）：
      - 基础必含：风格统一、无水印
      - allow_text=False：必须含「无文字」
      - allow_text=True ：必须含「无二维码」（替代无文字做兜底）
    返回 (ok, missing)。
    """
    p = prompt or ""
    missing = [t for t in REQUIRED_BASE if t not in p]
    if allow_text:
        if "无二维码" not in p:
            missing.append("无二维码")
    else:
        if "无文字" not in p:
            missing.append("无文字")
    return (len(missing) == 0, missing)


def ensure_prompt(agent_prompt, role="封面", account=None, brand_profile=None,
                  platform=None, extra="", allow_text=False):
    """
    agent 注入的 prompt 可能已经写完整（旧 JSON 是全英文完整 prompt）。
    已含全部必含字眼 -> 原样返回；否则用模板包装，保证风格锁生效。
    任何路径都会剥离与品牌锁冲突的色调词（防「四图四色」）。
    """
    p = (agent_prompt or "").strip()
    if not p:
        return _ensure_build("（待补主体描述）", role=role, account=account,
                             brand_profile=brand_profile, platform=platform,
                             extra=extra, allow_text=allow_text)
    ok, _ = validate_prompt(p, allow_text=allow_text)
    if ok:
        clean, conflicts = strip_conflict(p)
        if conflicts:
            print("⚠️ [品牌锁] 主体描述含与品牌色板冲突的词 %s，已自动剥离以防「四图四色」。"
                  % conflicts, file=sys.stderr)
        return clean
    return _ensure_build(p, role=role, account=account, brand_profile=brand_profile,
                         platform=platform, extra=extra, allow_text=allow_text)


def _ensure_build(subject, role="封面", account=None, brand_profile=None,
                  platform=None, extra="", allow_text=False):
    """剥离冲突色调词后再套模板（统一告警，避免四图四色）。"""
    clean, conflicts = strip_conflict(subject)
    if conflicts:
        print("⚠️ [品牌锁] 主体描述含与品牌色板冲突的词 %s，已自动剥离。" % conflicts,
              file=sys.stderr)
    return build_image_prompt(clean, role=role, account=account, brand_profile=brand_profile,
                              platform=platform, extra=extra, allow_text=allow_text)


# ---------------------------------------------------------------- 运营提示词卡片
_CARD_TEMPLATE = """# 生图提示词卡片（运营用）

> 账号：**{brand_label}**
> 平台：{platform}（{ratio}，{size}）
> 选题：{topic}
> 生图方式：**{mode}**
> 文字模式：**{text_mode}**

{mode_note}

## 使用步骤

1. 打开{douyin_or_doubao}（豆包 → 「图片」）→ 粘贴下方**完整提示词** → 生成
2. 一次出 4 张，挑最贴正文、构图最工整的那张
3. 检查成图：{text_step}
4. 用稿定设计 / Canva 套模板压标题（如需）→ 导出 {size}
5. 免费商用字体：思源黑体、阿里巴巴普惠体（别用来源不明字体，已有博主被索赔）

## 质量自检（发布前逐条打勾）

- [ ] 本篇所有图同一色板、同一滤镜（不出现「四图四色」）
- [ ] 标题文字在手机缩略图尺寸下清晰可读
- [ ] 尺寸 {size}，文字面积不超过画面 30%（超了会被判广告限流）
- [ ] 底部 15% 区域没放关键信息（会被平台标题遮挡）

{prompts_md}
"""


def build_operator_card(data, account=None, brand_profile=None, platform=None,
                        mode="提示词模式（未配置生图 API）", allow_text=None):
    """生成给运营的提示词卡片 markdown（prompt_only 模式下替代真实图片产出）。

    allow_text 不传时从 data["allow_text"] 读取（注入 JSON 顶层写 true 即走允许文字模式）；
    老 JSON 无此字段 = False，行为不变。
    """
    if allow_text is None:
        allow_text = bool((data or {}).get("allow_text", False))
    platform = platform or os.environ.get("IMAGE_PLATFORM") or DEFAULT_PLATFORM
    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS[DEFAULT_PLATFORM])
    b = _resolve_brand_dict(account, brand_profile)
    if not b:
        raise _accts.AccountError(
            "build_operator_card 需要 account 或 brand_profile（账号品牌锁缺失）。"
        )
    label = b.get("label") or account or "未命名账号"

    mode_note = (
        "当前**未配置生图 API**，系统按企业级降级策略只产出提示词：\n"
        "由你复制到豆包/即梦等免费网站生成图片，文字后期用设计工具压上。\n"
        "想改成全自动出图：在 `.env` 填 `IMAGE_API_KEY` / `IMAGE_API_BASE` / `IMAGE_MODEL` 即可（见 docs/生图配置指南.md）。"
        if "未配置" in mode else
        f"生图 API 已启用（{mode}），图片已自动生成；本卡片保留提示词备查与人工重出。"
    )
    if allow_text:
        mode_note += (
            "\n⚠️ 当前为**允许文字模式**：提示词允许模型在画面压大标题，但务必人工复核渲染的"
            "中文是否清晰准确；若文字扭曲/错字/漏字，仍按无文字底图处理、后期用设计工具压字。"
        )

    text_mode = "允许文字（allow_text=True）" if allow_text else "无文字底图（allow_text=False，默认）"
    text_step = (
        "允许模型压大字标题，但放大检查中文是否清晰、有无错字漏字；异常则改无文字底图后期压字"
        if allow_text else
        "下载成图（模型渲染中文可能偶有不完美，发布前务必放大检查文字清晰度）"
    )

    prompts_md = []
    cover = data.get("cover", {}) or {}
    if cover:
        raw = cover.get("prompt", "")
        conflicts = detect_style_conflict(raw)
        block = (
            "## 封面\n\n"
            f"**封面上要压的标题**：{cover.get('caption', '（待填）')}\n\n"
            f"**版式**：{cover.get('layout', '（待填）')}\n\n"
        )
        if conflicts:
            block += ("⚠️ **风格冲突告警**：主体描述含与品牌色板冲突的词 %s，"
                      "已自动剥离（防「四图四色」）。请主体只写内容与构图、不写色调。\n\n" % conflicts)
        block += "```text\n" + ensure_prompt(raw, role="封面",
                                            account=account, brand_profile=brand_profile,
                                            platform=platform, allow_text=allow_text) + "\n```\n"
        prompts_md.append(block)
    for i, im in enumerate(data.get("inner_images", []) or [], 1):
        raw = im.get("prompt", "")
        conflicts = detect_style_conflict(raw)
        block = (
            f"## 内页{i}\n\n"
            f"**图上要压的文字**：{im.get('caption', '（待填）')}\n\n"
            f"**版式**：{im.get('layout', '（待填）')}\n\n"
        )
        if conflicts:
            block += ("⚠️ **风格冲突告警**：主体描述含与品牌色板冲突的词 %s，"
                      "已自动剥离（防「四图四色」）。\n\n" % conflicts)
        block += "```text\n" + ensure_prompt(raw, role=f"内页{i}",
                                            account=account, brand_profile=brand_profile,
                                            platform=platform, allow_text=allow_text) + "\n```\n"
        prompts_md.append(block)

    # 文案风格锁展示（P2：成稿/提示词都遵守同一套口吻）
    copy = b.get("copy") or {}
    if copy:
        prompts_md.append(
            "## 本号文案风格锁（生成文案时遵守）\n\n"
            f"- 口吻：{copy.get('voice', '（未分析）')}\n"
            f"- 基调：{copy.get('tone', '（未分析）')}\n"
            f"- 偏好句式：{('、'.join(copy.get('preferred_phrases', []) or []) or '（未分析）')}\n"
            f"- 禁用词：{('、'.join(copy.get('banned_words', []) or []) or '（未分析）')}\n"
            f"- 风格提示：{copy.get('style_hint', '（未分析）')}\n"
        )

    return _CARD_TEMPLATE.format(
        brand_label=label,
        platform=platform,
        ratio=spec["ratio"],
        size=spec["size"],
        topic=data.get("topic") or data.get("title") or "（未命名选题）",
        mode=mode,
        text_mode=text_mode,
        mode_note=mode_note,
        douyin_or_doubao="抖音创作平台" if platform == "抖音" else "豆包",
        text_step=text_step,
        prompts_md="\n".join(prompts_md) or "（无配图方案）",
    )


def self_check():
    """自检：模板拼接 + 门禁是否生效（用合成 brand_profile，不依赖具体账号）。"""
    demo = {
        "label": "自检账号",
        "visual": {
            "palette": "主底 #FAF3E0 + 强调 #F4C0D1 + 中性 #C8A88A",
            "style": "极简干净、生活感",
            "lighting": "柔和自然光",
            "composition": "主体居中偏上",
            "negative": "无文字、无水印、无二维码、不堆砌元素",
        },
        "copy": {"voice": "第一人称亲切口吻", "tone": "轻松分享",
                 "preferred_phrases": ["我最近"], "banned_words": ["最"],
                 "style_hint": "口语化"},
    }
    # 默认无文字模式
    p = build_image_prompt("一支奶油色护手霜放在木质托盘上", role="封面", brand_profile=demo)
    ok, missing = validate_prompt(p, allow_text=False)
    # 允许文字模式
    p_txt = build_image_prompt("奶油白底信息卡，上方大号深棕色标题，三行竖向排列",
                               role="封面", brand_profile=demo, allow_text=True)
    ok_txt, missing_txt = validate_prompt(p_txt, allow_text=True)
    card = build_operator_card({"topic": "自检", "cover": {"prompt": "护手霜"}},
                               brand_profile=demo)
    ok2, missing2 = validate_prompt("一支护手霜（缺字眼）", allow_text=False)
    # 冲突剥离：中英文冲突词都会被剥离，品牌色板保住
    conflict_in = "a dark navy product with dramatic lighting on 深色背景, high contrast"
    conflict_out = ensure_prompt(conflict_in, role="封面", brand_profile=demo)
    return {
        "no_text_sample": p,
        "no_text_ok": ok,
        "no_text_missing": missing,
        "with_text_sample": p_txt,
        "with_text_ok": ok_txt,
        "with_text_missing": missing_txt,
        "gate_blocks_bad_prompt": (not ok2),
        "missing_on_bad": missing2,
        "card_has_copy_lock": ("本号文案风格锁" in card),
        "conflict_stripped": detect_style_conflict(conflict_in),
        "conflict_output_clean": (detect_style_conflict(conflict_out) == []),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
