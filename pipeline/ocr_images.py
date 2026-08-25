#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用本地 RapidOCR(ONNX, GPU 加速)批量提取 TOP10 内页图的文字。
速度 ~1.5s/张，远快于多模态大模型(27s/张)。
运行：python pipeline/ocr_images.py
输出：pipeline/top10_ocr.json  (结构化：每图文字)
      pipeline/top10_ocr.md    (合并 Markdown，便于直接阅读)
"""
import os
import sys
import json
import time

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("[ERROR] 缺少 Pillow/numpy，请先 pip install pillow numpy")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
DATA_FILE = os.path.join(PIPELINE, "top10_data.json")
OUT_JSON = os.path.join(PIPELINE, "top10_ocr.json")
OUT_MD = os.path.join(PIPELINE, "top10_ocr.md")


def load_engine():
    """延迟导入 RapidOCR，避免未安装时报错过早。"""
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _is_real_text(t):
    return bool(t and t.strip())


def main():
    if not os.path.exists(DATA_FILE):
        print(f"not found: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        notes = json.load(f)

    # 断点续跑
    existing = {}
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, "r", encoding="utf-8") as f:
                for it in json.load(f):
                    for pg in it.get("pages", []):
                        if _is_real_text(pg.get("text", "")):
                            existing[(it["note_id"], pg["page"])] = pg["text"]
        except Exception:
            existing = {}

    print(f"加载 OCR 引擎...", flush=True)
    engine = load_engine()

    results = []
    total = sum(len(n.get("images", [])) for n in notes)
    done = 0
    skipped = 0
    print(f"开始 OCR {total} 张图片，已复用 {len(existing)} 条", flush=True)

    md_blocks = []
    for note in notes:
        nid = note["note_id"]
        title = note["title"]
        item = {"rank": note["rank"], "note_id": nid, "title": title, "pages": []}
        md_blocks.append(f"\n## TOP{note['rank']}｜{title}\n(note_id: {nid})\n")
        for rel in note.get("images", []):
            path = os.path.normpath(os.path.join(ROOT, rel))
            page_num = os.path.splitext(os.path.basename(path))[0]
            key = (nid, page_num)
            if key in existing:
                text = existing[key]
                item["pages"].append({"page": page_num, "path": rel, "text": text})
                skipped += 1
                md_blocks.append(f"\n### 图 {page_num}\n{text}\n")
                continue
            if not os.path.exists(path):
                item["pages"].append({"page": page_num, "path": rel, "text": ""})
                continue
            # 用 PIL 读(兼容 webp 内容+.jpg 后缀)，转 numpy 给 RapidOCR
            with Image.open(path) as im:
                arr = np.array(im.convert("RGB"))
            res, _ = engine(arr)
            lines = [ln[1] for ln in res] if res else []
            text = "\n".join(lines)
            item["pages"].append({"page": page_num, "path": rel, "text": text})
            done += 1
            md_blocks.append(f"\n### 图 {page_num}\n{text}\n")
            print(f"  [{done}/{total}] {nid}/{page_num} 完成 ({len(lines)} 行)", flush=True)
            time.sleep(0.05)
        results.append(item)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        with open(OUT_MD, "w", encoding="utf-8") as f:
            f.write("# TOP10 内页图 OCR 文字提取\n\n")
            f.write("\n".join(md_blocks))

    print(f"全部完成：{OUT_JSON} / {OUT_MD}（新增 {done}，复用 {skipped}）", flush=True)


if __name__ == "__main__":
    main()
