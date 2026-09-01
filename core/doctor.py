# -*- coding: utf-8 -*-
"""core/doctor.py —— 预检医生（Preflight Doctor 模式，修复 D5）

python run_loop.py doctor [--ci]

设计：任何 critical 检查失败 → 退出码 1（CI 在 PR 阶段拦截「开箱即死」）；
optional 缺失只警告（克隆态本就缺私有适配器/数据，可跑本地模式）。

检查项：
  critical: Python>=3.10 / openpyxl / 核心模块(analytics,topic_pool,compliance,xhs_mvp) /
            公共内核 core / 测试样本 sample_search.csv
  optional: lark_oapi / 私有适配器 / .env / 竞品数据 CSV
"""
import glob
import importlib
import os
import sys
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)


class Check:
    def __init__(self, name: str, level: str, ok: bool, detail: str = ""):
        self.name = name
        self.level = level  # "critical" | "optional"
        self.ok = ok
        self.detail = detail


def _import_ok(mod: str):
    try:
        importlib.import_module(mod)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def run(ci: bool = False) -> int:
    checks: List[Check] = []

    # 1. Python 版本
    py = sys.version_info
    checks.append(Check("Python >= 3.10", "critical",
                        (py.major, py.minor) >= (3, 10),
                        "%d.%d.%d" % (py.major, py.minor, py.micro)))

    # 2. 依赖（openpyxl 必需；lark_oapi 仅飞书需要，可选）
    for mod, level in [("openpyxl", "critical"), ("lark_oapi", "optional"), ("requests", "optional")]:
        ok, d = _import_ok(mod)
        checks.append(Check("依赖 %s" % mod, level, ok, d))

    # 3. 公开核心模块可导入（来自 pipeline/，已加入 sys.path）
    for mod in ["analytics", "topic_pool", "compliance", "xhs_mvp"]:
        ok, d = _import_ok(mod)
        checks.append(Check("核心模块 %s" % mod, "critical", ok, d))

    # 4. 公共内核 core
    ok, d = _import_ok("core.local_runner")
    checks.append(Check("公共内核 core", "critical", ok, d))

    # 5. 可选私有适配器
    from core import di
    for name, present in di.detect_adapters().items():
        checks.append(Check(
            "可选适配器 %s (%s)" % (name, di.PRIVATE_SCRIPTS[name]),
            "optional", present,
            "已就绪" if present else "缺失（克隆后正常，降级本地模式）"))

    # 6. .env
    env_path = os.path.join(ROOT, ".env")
    checks.append(Check(".env 配置", "optional",
                        os.path.exists(env_path),
                        "存在" if os.path.exists(env_path) else "缺失（copy .env.example .env）"))

    # 7. 竞品数据 CSV
    csvs = glob.glob(os.path.join(
        ROOT, "tools", "MediaCrawler", "data", "xhs", "csv", "search_contents_*.csv"))
    checks.append(Check("竞品数据 CSV", "optional", bool(csvs),
                        "%d 个" % len(csvs) if csvs else "缺失（放入本地爬取数据）"))

    # 8. 测试样本（CI / 冒烟需要）
    sample = os.path.join(PIPE, "sample_search.csv")
    checks.append(Check("测试样本 sample_search.csv", "critical",
                        os.path.exists(sample),
                        "存在" if os.path.exists(sample) else "缺失（测试需要）"))

    # ---- 输出报告 ----
    print("\n========== run_loop doctor ==========")
    crit_fail = False
    for c in checks:
        mark = "✅" if c.ok else ("⚠️" if c.level == "optional" else "❌")
        print("  %s [%-8s] %s: %s" % (mark, c.level, c.name, c.detail))
        if (not c.ok) and c.level == "critical":
            crit_fail = True
    print("=====================================")

    if crit_fail:
        print("❌ 存在 critical 失败，无法运行。")
        return 1
    print("✅ 预检通过（optional 缺失仅为克隆态，可跑本地模式）。")
    return 0
