# -*- coding: utf-8 -*-
"""
run_baokuan_digest.py —— 爆款深挖一键入口（无飞书版）

把「脚本层」3 步串成一条命令，全自动、免费：
  ① 爬取：        crawl_trends.py                真实爬取关键词爆款（需登录态，可 --no-crawl 跳过）
  ② TOP10+下载：  digest_competitor.py --prepare-only  过滤 video → TOP10 → 下载全部图片 → top10_data.json
  ③ 内页 OCR：    ocr_images.py                  RapidOCR 提取内页文字 → top10_ocr.json / top10_ocr.md

加 --with-llm 再串联「大模型层」：
  ④ 深拆+规律+文案： llm_digest_ocr.py           基于 OCR 内页文字 → 爆款趋势规律_YYYYMMDD.md + 文案与标题_YYYYMMDD.md

产出（均在 pipeline/）：
  top10_data.json      结构化原料（含图片本地路径）
  pipeline/crawl_imgs/ 全部 TOP10 图片（封面+内页）
  top10_ocr.json/md    内页 OCR 文字（供大模型消化/人工阅读）
  爆款趋势规律_*.md    （--with-llm）TOP10 逐条深拆 + 4 维度方法论
  文案与标题_*.md      （--with-llm）5 条选题文案

用法：
  python pipeline/run_baokuan_digest.py                # 全跑（首次需扫码登录）
  python pipeline/run_baokuan_digest.py --no-crawl     # 跳过爬取，复用已有 CSV（补数据/重跑用）
  python pipeline/run_baokuan_digest.py --with-llm     # 脚本层 + 大模型深拆（推荐，一步到位）
  python pipeline/run_baokuan_digest.py --limit 10     # 指定 TOP N（默认 10）
  python pipeline/run_baokuan_digest.py --skip-ocr     # 只出原料，不跑 OCR

失败策略：爬取失败 → 警告后尝试复用已有 CSV；TOP10 失败 → 停止；OCR 失败 → 停止；
LLM 失败 → 警告不阻断（可事后单独跑 llm_digest_ocr.py）。
"""
import os
import sys
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
CRAWL_TRENDS = os.path.join(PIPELINE, "crawl_trends.py")
DIGEST = os.path.join(PIPELINE, "digest_competitor.py")
OCR = os.path.join(PIPELINE, "ocr_images.py")
LLM_DIGEST = os.path.join(PIPELINE, "llm_digest_ocr.py")
CSV_DIR = os.path.join(ROOT, "tools", "MediaCrawler", "data", "xhs", "csv")


def has_csv():
    if not os.path.isdir(CSV_DIR):
        return False
    for fn in os.listdir(CSV_DIR):
        if fn.startswith("search_contents_") and fn.endswith(".csv"):
            return True
    return False


def run_step(desc, cmd, timeout=1800):
    print(f"\n{'='*60}\n>>> {desc}\n{'='*60}", flush=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        rc = subprocess.call(cmd, cwd=ROOT, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ 「{desc}」超过 {timeout}s 未完成，已终止。", flush=True)
        return -1
    return rc


def main():
    ap = argparse.ArgumentParser(description="爆款深挖一键入口（无飞书）")
    ap.add_argument("--no-crawl", action="store_true", help="跳过爬取，复用已有 CSV")
    ap.add_argument("--limit", type=int, default=10, help="TOP N（默认 10）")
    ap.add_argument("--per-timeout", type=int, default=240, help="每条关键词爬取超时(秒)")
    ap.add_argument("--skip-ocr", action="store_true", help="只出原料，不跑 OCR")
    ap.add_argument("--with-llm", action="store_true",
                    help="脚本层跑完后，继续跑大模型深拆（为什么爆→规律→文案标题）")
    args = ap.parse_args()

    print("=== 爆款深挖一键入口（无飞书）===", flush=True)
    t0 = __import__("time").time()

    # ① 爬取
    if args.no_crawl:
        print("\n[--no-crawl] 跳过爬取，直接消费已有 CSV", flush=True)
    else:
        rc = run_step("① 真实爬取关键词爆款",
                      [sys.executable, CRAWL_TRENDS, "--per-timeout", str(args.per_timeout)])
        if rc != 0:
            print("  ⚠️ 爬取未成功（常见：登录态失效，需先手动扫码）。", flush=True)
            if has_csv():
                print("     检测到已有 CSV，继续用旧数据跑后续步骤；下次跑前请手动扫码刷新。", flush=True)
            else:
                print("     ERROR: 没有可用 CSV。请运行 `python pipeline/crawl_trends.py` 手动扫码后重跑。", flush=True)
                sys.exit(2)

    # ② TOP10 + 下载全部图片
    rc = run_step(f"② 过滤 video → TOP{args.limit} → 下载全部图片",
                  [sys.executable, DIGEST, "--prepare-only", "--limit", str(args.limit)])
    if rc != 0:
        print("\n❌ TOP10 原料生成失败，停止（这是后续步骤的输入）。", flush=True)
        sys.exit(1)

    # ③ 内页 OCR
    if args.skip_ocr:
        print("\n[--skip-ocr] 跳过 OCR，仅产出 top10_data.json + 图片。", flush=True)
    else:
        rc = run_step("③ 内页图片 OCR 提取文字（RapidOCR）",
                      [sys.executable, OCR])
        if rc != 0:
            print("\n❌ OCR 失败，停止。可用 --skip-ocr 先跳过（top10_data.json 已就绪）。", flush=True)
            sys.exit(1)

    # ④ 大模型深拆（可选）
    if args.with_llm:
        if args.skip_ocr:
            print("\n[--with-llm + --skip-ocr] 冲突：深拆需要 OCR 文字。已跳过 LLM。", flush=True)
        else:
            rc = run_step("④ 大模型深拆（为什么爆→规律→文案标题）",
                          [sys.executable, LLM_DIGEST])
            if rc != 0:
                print("\n  ⚠️ LLM 深拆失败（常见：API 限流 429 / 网络 / 超时）。", flush=True)
                print("     数据已就绪，可稍后单独补跑：python pipeline/llm_digest_ocr.py", flush=True)

    # 汇总
    elapsed = __import__("time").time() - t0
    today = __import__("datetime").datetime.now().strftime("%Y%m%d")
    print(f"\n{'='*60}\n✅ 一键入口完成，耗时 {elapsed/60:.1f} 分钟\n{'='*60}", flush=True)
    print("产出：", flush=True)
    for rel in ["pipeline/top10_data.json",
                "pipeline/top10_ocr.md" if not args.skip_ocr else None,
                "pipeline/top10_ocr.json" if not args.skip_ocr else None,
                "pipeline/crawl_imgs/",
                f"pipeline/爆款趋势规律_{today}.md" if args.with_llm and not args.skip_ocr else None,
                f"pipeline/文案与标题_{today}.md" if args.with_llm and not args.skip_ocr else None]:
        if rel:
            p = os.path.join(ROOT, rel)
            print(f"  - {rel}  ({'存在' if os.path.exists(p) else '缺失'})", flush=True)
    print("\n下一步：人工/大模型深拆 → 规律 → 文案标题（--with-llm 已自动完成）。", flush=True)


if __name__ == "__main__":
    main()
