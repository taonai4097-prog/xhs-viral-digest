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
