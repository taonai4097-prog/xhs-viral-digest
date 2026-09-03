# -*- coding: utf-8 -*-
"""core/local_runner.py —— 克隆即用的本地 CSV 模式（修复 D1/D3 开箱即死）

等价于 run_competitor_crawl.py 的 A-D + 选题池产出，但**只依赖公开核心模块**
（analytics / topic_pool），把结果写成本地 xlsx（热度看板.xlsx / 选题池.xlsx）。
无需飞书、无需任何被 .gitignore 的私有脚本。

这是公开仓库「开箱即用」的兜底路径：clone 下来、放一份竞品 CSV，即可跑出
热度看板 + 选题池（含推荐理由 + 热度指数），运营在本地就能拍板。
"""
import glob
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
if PIPE not in sys.path:
    sys.path.insert(0, PIPE)

import analytics as A  # noqa: E402
import topic_pool as T  # noqa: E402

DEFAULT_CSV_GLOB = os.path.join(
    ROOT, "tools", "MediaCrawler", "data", "xhs", "csv", "search_contents_*.csv"
)


def find_csvs(paths: List[str] = None) -> List[str]:
    """定位参与打分的竞品 CSV。

    - 显式传入 paths 时：只过滤存在的文件，不额外排除（调用方明确指定即信任）。
    - 自动 glob 时：若目录里同时存在真实 CSV 与 demo 样本（`*_demo*.csv`），
      demo 会被排除，避免 12 条虚构笔记混进真实选题打分（P2-5 防污染）；
      若**只有** demo 样本（新手首次试跑引导），仍允许跑通，否则引导链会断。
    """
    if paths:
        return [p for p in paths if os.path.exists(p)]
    found = sorted(glob.glob(DEFAULT_CSV_GLOB))
    real = [p for p in found if "_demo" not in os.path.basename(p)]
    return real if real else found


def run(top: int = 10, csv_paths: List[str] = None) -> Dict[str, Any]:
    """本地模式跑 A-D + 选题池。返回摘要 dict（含产出文件路径）。

    Raises:
        FileNotFoundError: 找不到任何竞品 CSV（克隆后未放入数据）。
    """
    csvs = find_csvs(csv_paths)
    if not csvs:
        raise FileNotFoundError(
            "未找到竞品 CSV（默认 %s）。克隆后请放入本地爬取数据，"
            "或用私有 run_competitor_crawl.py 爬取。" % DEFAULT_CSV_GLOB
        )

    notes: List[Dict[str, Any]] = []
    for c in csvs:
        notes += A.load_notes_from_csv(c)

    # score_notes 返回 (scored_list, baseline) 元组，需解包
    scored, _baseline = A.score_notes(notes)
    A.write_heat_board_xlsx(scored)

    rows = T.build_topic_pool(scored, top_n=top)

    # D6 反馈闭环回灌（H→A）：把上次回收的已发笔记表现贴回本轮选题池
    from core import metrics
    state = metrics.load_feedback_state()
    if state:
        hints = metrics.match_feedback(rows, state)
        if hints:
            T.apply_feedback(rows, hints)
            T.write_topic_pool_xlsx(rows)
            T.write_today_recommend(rows)
            print("  🔁 反馈闭环已回灌：%d 条选题带「历史表现」标记（见 选题池.xlsx）" % len(hints))

    T.write_topic_pool_xlsx(rows)
    T.write_today_recommend(rows)

    # V5 P2-3 内容支柱配比校验（运营视角）：基于「全部候选选题」的内容结构配比
    report = T.pillar_balance_report(scored)
    print("  📊 内容支柱配比（候选池 %d 篇，目标 30/30/25/15）：" % report["总计"])
    for k, v in report["分布"].items():
        print(f"     {k}: {v} 篇 ({report['占比'][k]}%)")
    for a in report["建议"]:
        print(f"     💡 {a}")

    return {
        "csvs": csvs,
        "n_raw": len(notes),
        "n_scored": len(scored),
        "heat_board": A.HEAT_BOARD_XLSX,
        "topic_pool": T.POOL_XLSX,
        "top": rows[:3],
    }
