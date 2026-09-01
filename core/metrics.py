# -*- coding: utf-8 -*-
"""core/metrics.py —— 反馈闭环回收器（实现 MetricsCollectorPort，D6 / ⑥ H→A 闭环）

把「已发笔记的真实互动数据」回收 → 回灌下一轮选题池 / 热度看板。

与 Open Core 一致：
- 公开核心只依赖本地 CSV：运营把已发笔记数据粘进 pipeline/metrics_feedback.csv；
- 若配置了 xiaohongshu_mcp.json，则走 MCP 自动回收（可选适配器，私有）；
- 无数据 / 无 MCP → 优雅跳过，绝不崩溃（呼应 fail-fast 但不打扰运营）。

用法：
  python run_loop.py feedback        # 回收 + 生成 feedback_state.json + 反馈闭环.md
  python run_loop.py run             # 下一轮自动读取 feedback_state，给命中选题打「历史表现」
"""
import os
import re
import csv
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")

FEEDBACK_CSV = os.path.join(PIPE, "metrics_feedback.csv")
FEEDBACK_STATE = os.path.join(PIPE, "feedback_state.json")
FEEDBACK_MD = os.path.join(PIPE, "反馈闭环.md")

# 运营粘贴的反馈 CSV 列
FIELDS = ["选题标题", "点赞", "收藏", "评论", "转发", "发布日期", "内容方向"]


def _coerce_int(v):
    if v is None:
        return 0
    s = str(v).strip().replace(",", "").replace("+", "")
    if s.endswith("万"):
        try:
            return int(float(s[:-1]) * 10000)
        except ValueError:
            return 0
    s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def read_feedback_csv(path: str = FEEDBACK_CSV) -> List[Dict[str, Any]]:
    """读运营粘贴的已发笔记反馈 CSV。文件缺失/为空返回 []（优雅跳过）。"""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            title = (row.get("选题标题") or "").strip()
            if not title:
                continue
            out.append({
                "title": title,
                "liked": _coerce_int(row.get("点赞")),
                "collected": _coerce_int(row.get("收藏")),
                "comment": _coerce_int(row.get("评论")),
                "share": _coerce_int(row.get("转发")),
                "date": (row.get("发布日期") or "").strip(),
                "direction": (row.get("内容方向") or "").strip(),
            })
    return out


def _keyword(title: str) -> str:
    """取标题关键词用于与下一轮选题匹配（去标点/数字，取前 8 字）。"""
    t = re.sub(r"[\s，。、！？!?.,/（）()\[\]【】\"'0-9]+", "", str(title))
    return t[:8]


def aggregate_feedback(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按关键词聚合已发笔记表现。返回 {keyword: {n, titles, avg_*}}。"""
    by_kw: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        kw = _keyword(r["title"]) or "未命名"
        by_kw.setdefault(kw, []).append(r)
    agg = {}
    for kw, items in by_kw.items():
        n = len(items)
        agg[kw] = {
            "n": n,
            "titles": [i["title"] for i in items],
            "avg_liked": round(sum(i["liked"] for i in items) / n),
            "avg_collected": round(sum(i["collected"] for i in items) / n),
            "avg_comment": round(sum(i["comment"] for i in items) / n),
            "avg_share": round(sum(i["share"] for i in items) / n),
        }
    return agg


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_feedback_state(rows: List[Dict[str, Any]],
                         out_json: Optional[str] = None,
                         out_md: Optional[str] = None) -> Dict[str, Any]:
    """聚合反馈 → 写 feedback_state.json + 人话 反馈闭环.md。返回 state dict。

    out_json/out_md 默认取模块级 FEEDBACK_STATE/FEEDBACK_MD（运行时解析，
    便于测试重定向；不用默认参数绑定旧值）。
    """
    agg = aggregate_feedback(rows)
    n = len(rows)
    out_json = out_json or FEEDBACK_STATE
    out_md = out_md or FEEDBACK_MD
    overall = {
        "已回收笔记数": n,
        "平均点赞": round(sum(r["liked"] for r in rows) / n) if n else 0,
        "平均收藏": round(sum(r["collected"] for r in rows) / n) if n else 0,
        "平均评论": round(sum(r["comment"] for r in rows) / n) if n else 0,
        "平均转发": round(sum(r["share"] for r in rows) / n) if n else 0,
    }
    state = {"version": 1, "overall": overall, "by_keyword": agg, "updated_at": _now()}
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [
        "# 反馈闭环（已发笔记 → 下一轮选题池）",
        "",
        "> 由 `python run_loop.py feedback` 生成（实现 D6 / ⑥ H→A 反馈闭环）。",
        "> 把已发笔记的真实数据回灌下一轮选题，让选题池从「猜」变成「有据」。",
        "",
        "## 总体表现",
        f"- 已回收笔记：**{overall['已回收笔记数']}** 篇",
        f"- 平均 赞 {overall['平均点赞']} / 藏 {overall['平均收藏']} / 评 {overall['平均评论']} / 转 {overall['平均转发']}",
        "",
        "## 按选题方向（回灌依据）",
    ]
    for kw, a in sorted(agg.items(),
                        key=lambda kv: kv[1]["avg_liked"] + kv[1]["avg_collected"],
                        reverse=True):
        lines.append(
            f"- **{kw}**（{a['n']}篇）：赞均{a['avg_liked']} / 藏均{a['avg_collected']} / "
            f"评均{a['avg_comment']} ｜ 代表：《{a['titles'][0]}》")
    lines += [
        "",
        "## 给下一轮选题池的提示",
        "- 下一轮 `run_loop.py run` 会自动读本文件，对标题关键词命中的选题打「历史表现」标记，运营拍板时参考。",
        "- 命中逻辑：已发笔记标题前 8 字 ≈ 选题标题前 8 字（模糊匹配，扩到 100+ 样本后更准，见 V5 P2-5）。",
    ]
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return state


class LocalCsvMetricsCollector:
    """公开可跑的本地 CSV 回收器（实现 MetricsCollectorPort.collect）。"""

    def collect(self, csv_path: str = FEEDBACK_CSV) -> Dict[str, Any]:
        rows = read_feedback_csv(csv_path)
        if not rows:
            return {"ok": True, "collected": 0, "skipped": True,
                    "message": ("未找到 metrics_feedback.csv（或为空），跳过反馈回收。"
                                 "把已发笔记数据粘进 pipeline/metrics_feedback.csv 后再跑 feedback。")}
        state = write_feedback_state(rows)
        return {"ok": True, "collected": len(rows), "skipped": False,
                "state": state,
                "message": f"已回收 {len(rows)} 篇已发笔记 → feedback_state.json + 反馈闭环.md"}


class McpMetricsCollector:
    """可选适配器：配置 xiaohongshu_mcp.json 时走 MCP 自动回收（私有实现）。

    真实回收由 agent 通过 xiaohongshu-mcp 取数并写回 metrics_feedback.csv，
    这里复用本地聚合，保证公开核心自洽可跑、不依赖私有件。
    """

    def __init__(self, cfg_path: str):
        self.cfg_path = cfg_path

    def collect(self, csv_path: str = FEEDBACK_CSV) -> Dict[str, Any]:
        return LocalCsvMetricsCollector().collect(csv_path)


def get_collector():
    """工厂：配置 MCP → MCP 回收器；否则本地 CSV 回收器。"""
    mcp_cfg = os.path.join(ROOT, "xiaohongshu_mcp.json")
    if os.path.exists(mcp_cfg):
        return McpMetricsCollector(mcp_cfg)
    return LocalCsvMetricsCollector()


def load_feedback_state(path: str = FEEDBACK_STATE) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def match_feedback(topics: List[Dict[str, Any]],
                   state: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """把反馈状态匹配到下一轮选题池，返回 {选题标题: 历史表现提示}。"""
    if not state:
        return {}
    by_kw = state.get("by_keyword", {})
    out: Dict[str, str] = {}
    for t in topics:
        title = t.get("选题标题", "")
        kw = _keyword(title)
        if kw in by_kw:
            a = by_kw[kw]
            out[title] = (f"历史表现：同类已发{a['n']}篇，赞均{a['avg_liked']}/"
                          f"藏均{a['avg_collected']}/评均{a['avg_comment']}（回灌参考）")
    return out
