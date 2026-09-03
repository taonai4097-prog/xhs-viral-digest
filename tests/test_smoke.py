# -*- coding: utf-8 -*-
"""tests/test_smoke.py —— 公开核心冒烟测试（修复 D5：测试抓不到开箱即死）

CI 在 PR 阶段运行：python -m pytest tests/ -q
覆盖：
  1) 公开核心模块可导入（analytics/topic_pool/compliance/xhs_mvp）
  2) doctor 预检无 critical 失败（克隆态可运行）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
for p in (ROOT, PIPE):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import di, local_runner, doctor, metrics  # noqa: E402


def test_core_modules_importable():
    import analytics  # noqa: F401
    import topic_pool  # noqa: F401
    import compliance  # noqa: F401
    import xhs_mvp  # noqa: F401
    assert True


def test_di_detect_adapters_keys():
    adapters = di.detect_adapters()
    assert set(adapters.keys()) == set(di.PRIVATE_SCRIPTS.keys())


def test_doctor_no_critical():
    rc = doctor.run(ci=True)
    assert rc == 0, "doctor 存在 critical 失败，克隆态不应如此"


def test_allow_text_switch_modes():
    """allow_text 开关：默认出无文字底图；allow_text=True 允许压标题但仍禁水印/二维码。
    回归：文字策略从写死「无文字」改为可切换开关（V6）。"""
    from image_prompt import build_image_prompt, validate_prompt

    brand = {"label": "验证账号",
             "visual": {"palette": "主底 #FAF3E0", "style": "简约", "lighting": "柔光",
                        "composition": "居中", "negative": "无文字、无水印"}}
    # 默认模式：含「无文字」、门禁过
    p_no = build_image_prompt("奶油白信息卡", brand_profile=brand)
    ok_no, _ = validate_prompt(p_no, allow_text=False)
    assert ok_no and "无文字" in p_no

    # 允许文字模式：不含「无文字」、含「无二维码」、门禁过
    p_yes = build_image_prompt("奶油白信息卡，上方大标题", brand_profile=brand, allow_text=True)
    ok_yes, _ = validate_prompt(p_yes, allow_text=True)
    assert ok_yes and "无二维码" in p_yes and "无文字" not in p_yes
    assert "标题大字清晰可读" in p_yes


def test_allow_text_from_inject_data():
    """注入 JSON 顶层 allow_text:true → 卡片头部显示「允许文字」；不写则行为不变。"""
    from image_prompt import build_operator_card

    brand = {"label": "验证账号",
             "visual": {"palette": "P", "style": "S", "lighting": "L",
                        "composition": "C", "negative": "N"}}
    data = {"topic": "选题", "cover": {"prompt": "信息卡", "caption": "标题", "layout": "居中"}}
    card_yes = build_operator_card(dict(data, allow_text=True), brand_profile=brand)
    assert "允许文字（allow_text=True）" in card_yes
    # 老 JSON 无该字段 = 默认无文字底图
    card_no = build_operator_card(data, brand_profile=brand)
    assert "无文字底图（allow_text=False，默认）" in card_no


def test_style_conflict_stripped():
    """主体描述含「深色背景」等冲突词 → 自动剥离且不进最终提示词（防四图四色）。"""
    from image_prompt import ensure_prompt, detect_style_conflict

    brand = {"label": "验证账号",
             "visual": {"palette": "主底 #FAF3E0", "style": "温暖", "lighting": "柔光",
                        "composition": "居中", "negative": "N"}}
    raw = "a dark navy product on 深色背景, high contrast"
    hits = detect_style_conflict(raw)
    assert "深色背景" in hits and "dark" in hits, "中英文冲突词都要能识别"
    out = ensure_prompt(raw, role="封面", brand_profile=brand)
    assert detect_style_conflict(out) == [], "剥离后不应残留冲突词"


def test_operator_card_with_brand_profile():
    """build_operator_card 用合成 brand_profile（含 visual 子块 + copy）应不崩且展示文案锁。
    回归：曾因 analyzer 产出的 visual 无 negative 键 -> brand_block KeyError。"""
    from image_prompt import build_operator_card, brand_block, build_image_prompt

    brand = {
        "label": "验证账号",
        "visual": {
            "palette": "主底 #FAF3E0 + 强调 #C85A3A + 中性 #C8A88A",
            "style": "温暖生活感",
            "lighting": "柔和自然光",
            "composition": "主体居中",
            # 故意不带 negative，验证 .get 兜底不会崩
        },
        "copy": {"voice": "第一人称亲切口吻", "tone": "轻松分享",
                 "preferred_phrases": ["我最近"], "banned_words": ["最"],
                 "style_hint": "带个人体验"},
    }
    data = {"topic": "验证选题",
            "cover": {"prompt": "奶油色护手霜", "caption": "标题", "layout": "居中"},
            "inner_images": [{"prompt": "使用对比图", "caption": "内页文字",
                              "layout": "上下"}]}
    card = build_operator_card(data, brand_profile=brand)
    assert "验证账号" in card
    assert "本号文案风格锁" in card, "运营卡片应展示文案风格锁"
    assert "无文字" in card, "提示词应带强制固定字眼"
    # 不带 negative 不报 KeyError
    bb = brand_block(brand_profile=brand)
    assert "负向约束" in bb
    p = build_image_prompt("护手霜", account=None, brand_profile=brand)
    assert "主底 #FAF3E0" in p


def test_inject_schema_compat_no_silent_skip():
    """旧 V6 注入 schema（subject/text）不得静默空：兼容层须把 subject 兜底为 prompt、
    text 兜底为 caption。

    回归 P0-3：V7 只读 prompt，旧 JSON（含仓库自带 demo）曾整段配图静默跳过、
    不报错、无迁移告警 —— 本用例即防此类「静默断裂」再次漏网。
    """
    from image_prompt import build_operator_card

    brand = {"label": "验证账号",
             "visual": {"palette": "P", "style": "S", "lighting": "L",
                        "composition": "C", "negative": "N"}}
    # 旧 schema（V6）：cover.subject / cover.text
    old = {"topic": "旧schema选题",
           "cover": {"subject": "奶油色护手霜特写", "text": "护手霜标题", "layout": "居中"},
           "inner_images": [{"subject": "使用对比图", "text": "内页文字", "layout": "上下"}]}
    card = build_operator_card(old, brand_profile=brand)
    assert "奶油色护手霜特写" in card, "旧 schema 的 subject 必须兜底为 prompt，不得静默空"
    assert "护手霜标题" in card, "旧 schema 的 text 必须兜底为 caption"
    assert "使用对比图" in card, "内页 subject 必须兜底"

    # 新 schema 不因兼容层回退（prompt/caption 仍照常生效）
    new = {"topic": "新schema选题",
           "cover": {"prompt": "奶油色护手霜", "caption": "标题", "layout": "居中"}}
    card_new = build_operator_card(new, brand_profile=brand)
    assert "奶油色护手霜" in card_new and "标题" in card_new


def test_inject_schema_empty_prompts_warn_no_silent_placeholder():
    """prompt/subject 两者皆空时：必须向 stderr 告警 + 卡片不得静默产出「（待补主体描述）」，
    而应含醒目的缺主体提示，并照常布局（供运营一眼看出缺料）。

    回归 N-3：默认提示词卡片路径（prompt_only，开源 clone 无生图 API 的默认路径）
    空值时静默塞占位符、零告警 —— 比 P0-3 的"跳过"更隐蔽，本用例锁死它。
    """
    import io
    import contextlib

    from image_prompt import build_operator_card

    brand = {"label": "验证账号",
             "visual": {"palette": "P", "style": "S", "lighting": "L",
                        "composition": "C", "negative": "N"}}
    empty = {"topic": "空值选题",
             "cover": {"layout": "居中"},
             "inner_images": [{"layout": "上下"}, {"caption": "有字无主体"}]}

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        card = build_operator_card(empty, brand_profile=brand)

    # ① 空值必须告警（封面 + 每张缺主体的内页）
    warn = err.getvalue()
    assert "封面" in warn and "既无 prompt 也无 subject" in warn, "封面空值应 stderr 告警"
    assert "内页1" in warn and "既无 prompt 也无 subject" in warn, "内页1 空值应 stderr 告警"
    assert "内页2" in warn and "既无 prompt 也无 subject" in warn, \
        "内页2 有 caption 但无 prompt/subject，仍应告警"

    # ② 卡片内不得是旧的「（待补主体描述）」静默占位，须含醒目的缺主体提示
    assert "缺主体描述" in card, "空值应在卡片内以 '缺主体描述' 醒目提示运营补料"
