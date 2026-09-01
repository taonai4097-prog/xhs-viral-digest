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

对外接口：
  build_image_prompt(subject, role, brand, platform) -> 完整提示词
  ensure_prompt(agent_prompt, ...)                  -> 已合规则原样返回，否则包装
  validate_prompt(prompt)                           -> (ok, missing_tokens)
  build_operator_card(data, brand, platform)        -> 给运营的提示词卡片(markdown)
"""
from __future__ import annotations

import os
import re
import sys

# ---------------------------------------------------------------- 平台规格
PLATFORM_SPECS = {
    "小红书": {"ratio": "3:4 竖版", "size": "1080x1440"},
    "抖音": {"ratio": "9:16 竖版", "size": "1080x1920"},
}
DEFAULT_PLATFORM = "小红书"

# ---------------------------------------------------------------- 品牌风格锁
# 每个账号一套：配色 / 风格 / 光照 / 构图 / 负向约束。
# 新增账号只需在这里加一项（或由 brand_kits.json 覆盖，见 load_brand_kits）。
BRAND_KITS = {
    "小依依依": {
        "label": "小依依依（小红书 · 个人IP）",
        "palette": "奶油白 #FAF3E0 主底 + 柔粉 #F4C0D1 强调 + 暖木 #C8A88A 点缀",
        "style": "极简干净、生活感、真实不做作，避免广告感与过度精修",
        "lighting": "柔和自然光从左上打入，轻微阴影，无硬光斑",
        "composition": "主体居中偏上占画面 60% 以上，背景简洁不抢戏",
        "negative": "无文字、无水印、无二维码、不堆砌元素",
    },
    "极光科技": {
        "label": "极光科技（抖音 · 机构号）",
        "palette": "深灰 #2D2D2D 主底 + 科技蓝 #4A90D9 强调 + 荧光绿 #00D4AA 点缀",
        "style": "极简信息图风、专业前沿，深色科技质感",
        "lighting": "均匀柔光，冷色调，轻微渐变光晕",
        "composition": "主体居中，顶部三分之一留干净空白给标题",
        "negative": "无文字、无水印、不堆砌元素、不用花体艺术字",
    },
}
DEFAULT_BRAND = "小依依依"

# ---------------------------------------------------------------- 强制固定字眼
# 用户要求「强制加固定提示词字眼」：每次生成必须带上，并在 validate_prompt 里卡关。
FIXED_SUFFIX = "风格统一, 无文字, 无水印, 高清细节, 与同篇其他图同色板同滤镜"
REQUIRED_TOKENS = ["风格统一", "无文字", "无水印"]

# 品牌锁冲突词（V5 红队 P2-1）：主体描述若自带这些词，会覆盖品牌色板 → 四图四色。
# 生成时自动剥离并告警，确保「同色板」铁律不被主体描述破坏。
STYLE_CONFLICT_TOKENS = [
    "dark", "dramatic", "high contrast", "neon",
    "深黑", "暗黑", "高对比", "高反差", "霓虹", "冷艳",
]

# 外部可覆盖的品牌表（JSON，字段同 BRAND_KITS 的 value）
BRAND_KITS_FILE = "brand_kits.json"


def load_brand_kits():
    """允许用 pipeline/brand_kits.json 覆盖内置品牌表（不改代码换色板）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BRAND_KITS_FILE)
    if not os.path.exists(path):
        return BRAND_KITS
    try:
        import json
        with open(path, encoding="utf-8") as f:
            ext = json.load(f)
        merged = dict(BRAND_KITS)
        merged.update(ext or {})
        return merged
    except Exception:
        return BRAND_KITS


def resolve_brand(brand=None):
    """按名字模糊匹配品牌（支持 '小依依依' / '小依依依（小红书）' 等写法）。"""
    kits = load_brand_kits()
    if not brand:
        brand = os.environ.get("IMAGE_BRAND") or os.environ.get("ACCOUNT_NAME") or DEFAULT_BRAND
    b = str(brand).strip()
    if b in kits:
        return b, kits[b]
    for k in kits:
        if k and (k in b or b in k):
            return k, kits[k]
    return DEFAULT_BRAND, kits[DEFAULT_BRAND]


def brand_block(brand=None):
    """把品牌规范压成一段固定的 style block（每次生成原样拼接，保证一致）。"""
    name, b = resolve_brand(brand)
    return (
        f"配色：{b['palette']}；"
        f"风格：{b['style']}；"
        f"光照：{b['lighting']}；"
        f"构图：{b['composition']}；"
        f"负向约束：{b['negative']}"
    )


def build_image_prompt(subject, role="封面", brand=None, platform=None, extra=""):
    """
    拼接完整提示词 = 平台规格 + 品牌风格锁 + 画面主体 + 强制后缀。
    subject：只写「画面里有什么」，不要写风格（风格由品牌锁统一管）。
    """
    platform = platform or os.environ.get("IMAGE_PLATFORM") or DEFAULT_PLATFORM
    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS[DEFAULT_PLATFORM])
    parts = [
        f"{platform}{role}，{spec['ratio']}，{spec['size']}",
        brand_block(brand),
        f"画面主体：{subject}",
    ]
    if extra:
        parts.append(str(extra).strip())
    parts.append(FIXED_SUFFIX)
    return "；".join(parts)


def validate_prompt(prompt):
    """质量门禁：必含字眼缺失即拦截。返回 (ok, missing)。"""
    p = prompt or ""
    missing = [t for t in REQUIRED_TOKENS if t not in p]
    return (len(missing) == 0, missing)


def detect_style_conflict(text):
    """检测主体/提示词里与品牌锁冲突的色调词（V5 红队 P2-1）。返回命中词列表。"""
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


def ensure_prompt(agent_prompt, role="封面", brand=None, platform=None, extra=""):
    """
    agent 注入的 prompt 可能已经写完整（旧 JSON 是全英文完整 prompt）。
    已含全部必含字眼 -> 原样返回；否则用模板包装，保证风格锁生效。
    任何路径都会剥离与品牌锁冲突的色调词（V5 红队 P2-1，防四图四色）。
    """
    p = (agent_prompt or "").strip()
    if not p:
        return _ensure_build("（待补主体描述）", role=role, brand=brand,
                             platform=platform, extra=extra)
    ok, _ = validate_prompt(p)
    if ok:
        clean, conflicts = strip_conflict(p)
        if conflicts:
            print("⚠️ [品牌锁] 主体描述含与品牌色板冲突的词 %s，已自动剥离以防「四图四色」。"
                  % conflicts, file=sys.stderr)
        return clean
    return _ensure_build(p, role=role, brand=brand, platform=platform, extra=extra)


def _ensure_build(subject, role="封面", brand=None, platform=None, extra=""):
    clean, conflicts = strip_conflict(subject)
    if conflicts:
        print("⚠️ [品牌锁] 主体描述含与品牌色板冲突的词 %s，已自动剥离。" % conflicts,
              file=sys.stderr)
    return build_image_prompt(clean, role=role, brand=brand, platform=platform, extra=extra)


# ---------------------------------------------------------------- 运营提示词卡片
_CARD_TEMPLATE = """# 生图提示词卡片（运营用）

> 账号：**{brand_label}**
> 平台：{platform}（{ratio}，{size}）
> 选题：{topic}
> 生图方式：**{mode}**

{mode_note}

## 使用步骤

1. 打开{douyin_or_doubao}（豆包 → 「图片」）→ 粘贴下方**完整提示词** → 生成
2. 一次出 4 张，挑最贴正文、构图最工整的那张
3. **下载不带任何文字的底图**（模型渲染中文必乱码，所以提示词已强制「无文字」）
4. 用稿定设计 / Canva 套模板压标题 → 导出 {size}
5. 免费商用字体：思源黑体、阿里巴巴普惠体（别用来源不明字体，已有博主被索赔）

## 质量自检（发布前逐条打勾）

- [ ] 本篇所有图同一色板、同一滤镜（不出现「四图四色」）
- [ ] 标题文字在手机缩略图尺寸下清晰可读
- [ ] 尺寸 {size}，文字面积不超过画面 30%（超了会被判广告限流）
- [ ] 底部 15% 区域没放关键信息（会被平台标题遮挡）

{prompts_md}
"""


def build_operator_card(data, brand=None, platform=None, mode="提示词模式（未配置生图 API）"):
    """生成给运营的提示词卡片 markdown（prompt_only 模式下替代真实图片产出）。"""
    platform = platform or os.environ.get("IMAGE_PLATFORM") or DEFAULT_PLATFORM
    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS[DEFAULT_PLATFORM])
    name, b = resolve_brand(brand)

    mode_note = (
        "当前**未配置生图 API**，系统按企业级降级策略只产出提示词：\n"
        "由你复制到豆包/即梦等免费网站生成图片，文字后期用设计工具压上。\n"
        "想改成全自动出图：在 `.env` 填 `IMAGE_API_KEY` / `IMAGE_API_BASE` / `IMAGE_MODEL` 即可（见 docs/生图配置指南.md）。"
        if "未配置" in mode else
        f"生图 API 已启用（{mode}），图片已自动生成；本卡片保留提示词备查与人工重出。"
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
                                            brand=name, platform=platform) + "\n```\n"
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
                                            brand=name, platform=platform) + "\n```\n"
        prompts_md.append(block)

    return _CARD_TEMPLATE.format(
        brand_label=b["label"],
        platform=platform,
        ratio=spec["ratio"],
        size=spec["size"],
        topic=data.get("topic") or data.get("title") or "（未命名选题）",
        mode=mode,
        mode_note=mode_note,
        douyin_or_doubao="抖音创作平台" if platform == "抖音" else "豆包",
        prompts_md="\n".join(prompts_md) or "（无配图方案）",
    )


def self_check():
    """自检：模板拼接 + 门禁是否生效 + 品牌锁冲突剥离（V5 红队 P2-1）。"""
    p = build_image_prompt("一支奶油色护手霜放在木质托盘上", role="封面", brand="小依依依")
    ok, missing = validate_prompt(p)
    ok2, missing2 = validate_prompt("一支护手霜（缺字眼）")
    # 冲突剥离：主体自带 dark/dramatic 会被自动剥离，品牌色板保住
    conflict_in = "a dark navy product with dramatic lighting, high contrast"
    conflict_out = ensure_prompt(conflict_in, role="封面", brand="小依依依")
    return {
        "prompt_sample": p,
        "built_ok": ok,
        "missing_on_built": missing,
        "gate_blocks_bad_prompt": (not ok2),
        "missing_on_bad": missing2,
        "conflict_input": conflict_in,
        "conflict_stripped": detect_style_conflict(conflict_in),
        "conflict_output_clean": (detect_style_conflict(conflict_out) == []),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
