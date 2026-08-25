# -*- coding: utf-8 -*-
"""
crawl_trends.py —— 仅真实爬取关键词爆款，产出 CSV（不碰飞书 / 不跑旧分析）

对齐账号方向的关键词写在 pipeline/competitor_targets.json。
本脚本只负责「真实爬取」，深拆与出报告交给 digest_competitor.py。

用法：
  python pipeline/crawl_trends.py                  # 爬全部关键词
  python pipeline/crawl_trends.py --index 0       # 只跑第 1 条（测登录态）
  python pipeline/crawl_trends.py --per-timeout 240
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_competitor_crawl as rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=None,
                    help="只跑第 N 条关键词（0基），用于快速验证登录态")
    ap.add_argument("--per-timeout", type=int, default=240,
                    help="每条关键词爬取超时(秒)，超时视为登录态失效")
    args = ap.parse_args()

    targets = rc.load_targets(rc.DEFAULT_TARGETS)
    if args.index is not None:
        targets = [targets[args.index]]

    print(f"=== 真实爬取 {len(targets)} 条关键词（search 模式，仅图文由下游过滤）===")
    for i, t in enumerate(targets, 1):
        kw = t.get("keyword")
        print(f"\n[{i}/{len(targets)}] 关键词：{kw}")
        rc.patch_base_config("search")
        rc.patch_xhs_config(t)
        rc.run_mediacrawler("search", timeout=args.per_timeout)

    print("\n=== 爬取结束，CSV 落在 tools/MediaCrawler/data/xhs/csv/ ===")


if __name__ == "__main__":
    main()
