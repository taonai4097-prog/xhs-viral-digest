# -*- coding: utf-8 -*-
"""
digest_competitor.py —— 数据准备：真实爆款 → TOP10 → 下载全部图片 → top10_data.json

职责边界（本仓库只有这一种模式 --prepare-only）：
  读取 tools/MediaCrawler/data/xhs/csv/search_contents_*.csv（真实爬取）,
  仅保留本账号方向关键词、仅图文（过滤 video），按互动数取 TOP10，
  下载封面 + 全部内页图到 pipeline/crawl_imgs/{note_id}/，
  导出结构化原料 pipeline/top10_data.json。

深拆（为什么爆 → 规律 → 文案标题）不在这——请走 llm_digest_ocr.py（OCR 内页文字 + 大模型）。
原 GLM-4V 视觉深拆 deep_digest 已移除（与 OCR 主链路功能重复且输出同名文件，MECE 冲突）。

用法：
  python pipeline/digest_competitor.py                  # TOP10 数据准备
  python pipeline/digest_competitor.py --limit 5        # 只取 TOP5
"""
import os, sys, csv, json, re, argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MC_CSV_DIR = os.path.join(ROOT, "tools", "MediaCrawler", "data", "xhs", "csv")
IMG_DIR = os.path.join(ROOT, "pipeline", "crawl_imgs")
TARGETS_FILE = os.path.join(ROOT, "pipeline", "competitor_targets.json")


def load_keywords():
    """惰性读取关键词清单（search 模式）-> keyword 列表，缺失/无效时给出友好报错。"""
    if not os.path.exists(TARGETS_FILE):
        print(f"ERROR: 找不到关键词清单 {TARGETS_FILE}")
        print("       请复制 pipeline/competitor_targets.example.json 为 competitor_targets.json 并填入你的关键词")
        sys.exit(1)
    with open(TARGETS_FILE, encoding="utf-8") as f:
        targets = json.load(f)
    if not isinstance(targets, list):
        targets = [targets]
    kws = []
    for t in targets:
        if t.get("mode", "search") != "search":
            print(f"  [警告] 跳过条目「{t.get('name', '?')}」：本版本仅支持 search 模式")
            continue
        k = t.get("keyword")
        if not k:
            print(f"  [警告] 跳过条目「{t.get('name', '?')}」：缺少 keyword 字段")
            continue
        kws.append(k)
    if not kws:
        print("ERROR: 关键词清单中没有有效的 search 关键词，请检查 competitor_targets.json")
        sys.exit(1)
    return kws


def parse_count(s):
    if s is None:
        return 0
    s = str(s).strip().replace(",", "")
    if not s:
        return 0
    mult = 10000 if ("万" in s.lower() or s.lower().endswith("w")) else 1
    num = re.findall(r"[\d.]+", s)
    return int(float(num[0]) * mult) if num else 0


def load_notes():
    rows = []
    if not os.path.isdir(MC_CSV_DIR):
        print("ERROR: 找不到爬取目录", MC_CSV_DIR)
        print("       请先运行 python pipeline/crawl_trends.py 爬取，或用 --no-crawl 复用已有 CSV")
        sys.exit(1)
    keywords = load_keywords()
    for fn in os.listdir(MC_CSV_DIR):
        if not fn.startswith("search_contents_") or not fn.endswith(".csv"):
            continue
        fp = os.path.join(MC_CSV_DIR, fn)
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                kw = (r.get("source_keyword") or "").strip()
                if kw not in keywords:
                    continue
                if (r.get("type") or "").strip().lower() == "video":
                    continue
                rows.append(r)
    print(f"  过滤后有效图文笔记：{len(rows)} 条（关键词命中 + 非视频）")
    # 按 note_id 去重（前台已爬过的关键词后台会重爬）
    seen, uniq = set(), []
    for r in rows:
        k = r.get("note_id")
        if k and k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    if len(uniq) != len(rows):
        print(f"  去重后：{len(uniq)} 条（去掉 {len(rows) - len(uniq)} 条重复）")
    return uniq


def top_n(rows, limit=10):
    for r in rows:
        r["_liked"] = parse_count(r.get("liked_count"))
        r["_collected"] = parse_count(r.get("collected_count"))
        r["_score"] = r["_liked"] + r["_collected"]
    rows.sort(key=lambda x: x["_score"], reverse=True)
    return rows[:limit]


def download_all_images(r):
    """下载一条笔记的全部图片，按 note_id 分目录存储，返回 [(序号, 本地路径)]。断点续存：已存在的跳过。"""
    nid = r.get("note_id") or "x"
    save_dir = os.path.join(IMG_DIR, nid)
    os.makedirs(save_dir, exist_ok=True)
    urls = [u.strip() for u in (r.get("image_list") or "").split(",") if u.strip()]
    if not urls:
        return []
    result = []
    for idx, u in enumerate(urls, 1):
        out = os.path.join(save_dir, f"{idx}.jpg")
        if os.path.exists(out):
            result.append((idx, out))
            continue
        try:
            import requests
            with requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status_code == 200:
                    with open(out, "wb") as f:
                        f.write(resp.content)
                    result.append((idx, out))
        except Exception as e:
            print(f"    [图{idx}下载失败] {nid}: {e}")
    return result


def main():
    ap = argparse.ArgumentParser(description="数据准备：过滤→TOP10→下载全部图片→top10_data.json")
    ap.add_argument("--limit", type=int, default=10, help="TOP N（默认 10）")
    args = ap.parse_args()
    os.makedirs(IMG_DIR, exist_ok=True)

    print("=== 数据准备：真实爆款 TOP + 下载全部图片 ===")
    rows = load_notes()
    if not rows:
        print("ERROR: 没有命中关键词的笔记，请先跑 crawl_trends.py 或确认 competitor_targets.json 关键词")
        sys.exit(1)
    top = top_n(rows, args.limit)
    print(f"  TOP{len(top)} 已选出（赞+藏排序）")

    # 下载封面 + 全部内页图 + 导出结构化原料
    for i, r in enumerate(top, 1):
        imgs = download_all_images(r)
        r["_images"] = [os.path.relpath(p, ROOT) for _, p in imgs]
        print(f"    [{i}/{len(top)}] {(r.get('title') or '')[:18]} -> 共{len(imgs)}张图")

    data = [{
        "rank": i + 1,
        "note_id": r.get("note_id"),
        "title": r.get("title"),
        "nickname": r.get("nickname"),
        "liked": r["_liked"],
        "collected": r["_collected"],
        "tags": r.get("tag_list"),
        "desc": r.get("desc"),
        "note_url": r.get("note_url"),
        "images": r.get("_images", []),
        "image_list": [u.strip() for u in (r.get("image_list") or "").split(",") if u.strip()],
    } for i, r in enumerate(top)]
    out = os.path.join(ROOT, "pipeline", "top10_data.json")
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ 原料已导出：{out}（{len(top)} 条；全部图片在 pipeline/crawl_imgs/{{note_id}}/）")
    print("   下一步：python pipeline/ocr_images.py 提取内页文字 -> python pipeline/llm_digest_ocr.py 深拆出文案")


if __name__ == "__main__":
    main()
