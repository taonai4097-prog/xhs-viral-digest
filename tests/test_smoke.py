# -*- coding: utf-8 -*-
"""tests/test_smoke.py —— 公开核心冒烟测试（修复 D5：测试抓不到开箱即死）

CI 在 PR 阶段运行：python -m pytest tests/ -q
覆盖：
  1) 公开核心模块可导入（analytics/topic_pool/compliance/xhs_mvp）
  2) 本地 CSV 模式（core.local_runner）在合成样本上跑通并产出选题池
  3) doctor 预检无 critical 失败（克隆态可运行）
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
for p in (ROOT, PIPE):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import di, local_runner, doctor  # noqa: E402


def test_core_modules_importable():
    import analytics  # noqa: F401
    import topic_pool  # noqa: F401
    import compliance  # noqa: F401
    import xhs_mvp  # noqa: F401
    assert True


def test_local_runner_on_sample():
    sample = os.path.join(PIPE, "sample_search.csv")
    assert os.path.exists(sample), "测试样本 sample_search.csv 必须存在"
    summary = local_runner.run(top=5, csv_paths=[sample])
    assert summary["n_raw"] > 0
    assert summary["n_scored"] > 0
    # 反刷量样本(sample_1008)应被标风险但不至于崩
    assert os.path.exists(summary["topic_pool"])


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
