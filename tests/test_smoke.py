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

from core import di, local_runner, doctor, metrics  # noqa: E402


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


def test_feedback_loop(tmp_path):
    """D6 反馈闭环：回收 CSV → 聚合 → 回灌匹配下一轮选题（H→A）。"""
    import csv as _csv
    fb = tmp_path / "metrics_feedback.csv"
    with open(fb, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["选题标题", "点赞", "收藏", "评论", "转发", "发布日期", "内容方向"])
        w.writerow(["日均不到1块护牙方法", 1200, 530, 61, 30, "2026-08-20", "低成本"])
        w.writerow(["口臭是病不是小事", 800, 1112, 40, 12, "2026-08-22", "病症警示"])

    # 重定向生成产物到临时目录，避免污染仓库
    metrics.FEEDBACK_STATE = str(tmp_path / "feedback_state.json")
    metrics.FEEDBACK_MD = str(tmp_path / "反馈闭环.md")

    res = metrics.LocalCsvMetricsCollector().collect(csv_path=str(fb))
    assert res["ok"]
    assert res["collected"] == 2
    assert os.path.exists(metrics.FEEDBACK_STATE)

    # 回灌匹配：下一轮选题标题关键词命中已发笔记
    topics = [{"选题标题": "日均不到1块护牙方法（四件套篇）"}]
    hints = metrics.match_feedback(topics, res["state"])
    assert "日均不到1块护牙方法（四件套篇）" in hints
    assert "历史表现" in hints["日均不到1块护牙方法（四件套篇）"]

    # topic_pool.apply_feedback 能把提示贴回选题行
    import topic_pool as T
    rows = [{"选题标题": "日均不到1块护牙方法（四件套篇）", "推荐理由": "原理由"}]
    T.apply_feedback(rows, hints)
    assert "历史表现" in rows[0]
    assert "历史表现" in rows[0]["推荐理由"]


def test_feedback_collector_no_data(tmp_path):
    """无反馈数据 → 优雅跳过（绝不崩溃），符合 fail-fast 不打扰原则。"""
    metrics.FEEDBACK_STATE = str(tmp_path / "fs.json")
    metrics.FEEDBACK_MD = str(tmp_path / "fb.md")
    res = metrics.LocalCsvMetricsCollector().collect(csv_path=str(tmp_path / "missing.csv"))
    assert res["skipped"] is True
    assert res["collected"] == 0


def test_brand_lock_conflict_strip():
    """V5 红队 P2-1：主体自带 dark/dramatic 等冲突词应被自动剥离。"""
    import image_prompt as IP
    out = IP.ensure_prompt("a dark navy product with dramatic lighting, high contrast",
                           role="封面", brand="小依依依")
    assert IP.detect_style_conflict(out) == [], "品牌锁冲突词未被剥离"
    # 正常主体不受影响
    ok = IP.ensure_prompt("一支奶油色护手霜放在木质托盘上", brand="小依依依")
    assert IP.detect_style_conflict(ok) == []


# ======================= V5 P2-3/4/5 增长三件套 =======================
def test_pillar_classification():
    """P2-3：4 大内容支柱关键词打标正确。"""
    import topic_pool as T
    assert T.classify_pillar("口臭是病不是小事") == "①病症警示/自检"
    assert T.classify_pillar("日均不到1块护牙方法") == "②低成本实操清单"
    assert T.classify_pillar("以为在护牙其实在伤牙") == "③误区纠正"
    assert T.classify_pillar("我是口腔医学生") == "④人设/幕后"
    # 无命中关键词 → 兜底④人设/幕后
    assert T.classify_pillar("今天天气真好") == "④人设/幕后"


def test_pillar_balance_report():
    """P2-3：配比报告结构正确，偏食时给出补/减建议。"""
    import topic_pool as T
    # 偏食：全 ① → 其余三支柱应被建议补充
    rows = [{"内容支柱": "①病症警示/自检"} for _ in range(5)]
    rep = T.pillar_balance_report(rows)
    assert rep["总计"] == 5
    assert sum(rep["分布"].values()) == 5
    assert any("建议补" in a for a in rep["建议"])
    # 均衡：四支柱各 1 → 应判定均衡
    balanced = [{"内容支柱": k} for k in
                ["①病症警示/自检", "②低成本实操清单", "③误区纠正", "④人设/幕后"]]
    rep2 = T.pillar_balance_report(balanced)
    assert any("均衡" in a for a in rep2["建议"])


def test_heat_includes_usefulness():
    """P2-4：热度分融合收藏率有用性 + 双高加权，新字段齐全且在 0-100。"""
    import analytics as A
    sample = os.path.join(PIPE, "sample_search.csv")
    notes = A.load_notes_from_csv(sample)
    scored, _ = A.score_notes(notes)
    assert scored, "打分不应为空"
    for n in scored:
        assert "useful_pct" in n and "engage_pct" in n and "double_high" in n
        assert isinstance(n["double_high"], bool)
        assert 0 <= n["heat_score"] <= 100, "热度分越界"
    # 注入的双高种子应至少命中 1 条，证明加权路径真实生效
    assert any(n["double_high"] for n in scored), "双高加权路径未被触发"


def test_sample_size():
    """P2-5：竞品样本已扩到 100+，热度基线才稳。"""
    sample = os.path.join(PIPE, "sample_search.csv")
    assert os.path.exists(sample)
    with open(sample, encoding="utf-8-sig", newline="") as f:
        n = sum(1 for _ in __import__("csv").reader(f)) - 1  # 去掉表头
    assert n >= 100, f"样本仅 {n} 行，需扩到 100+（当前 V5 P2-5 要求）"

