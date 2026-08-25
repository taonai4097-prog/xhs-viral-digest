# -*- coding: utf-8 -*-
"""
llm_digest_ocr.py —— 基于 OCR 内页文字做「为什么爆 → 规律 → 文案标题」（大模型层）

输入：
  pipeline/top10_data.json   结构化原料（标题/互动/标签/正文/链接）
  pipeline/top10_ocr.json    全部内页 OCR 文字（真正的内容主体）

输出（与 digest_competitor.py 同命名，但内容是 OCR 内页版）：
  pipeline/爆款趋势规律_YYYYMMDD.md   TOP10 逐条深拆（含内页结构）+ 4 维度方法论
  pipeline/文案与标题_YYYYMMDD.md     5 条选题（标题+正文+标签，无图、无生图提示词）

用法：
  python pipeline/llm_digest_ocr.py                # 正常跑（约 5-10 分钟，10+ 次 GLM 调用）
  python pipeline/llm_digest_ocr.py --no-rules     # 只出深拆，不提炼规律/文案（调试用）
"""
import os, sys, json, time, argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import glm_content_gen as glm

DATA_FILE = os.path.join(HERE, "top10_data.json")
OCR_FILE = os.path.join(HERE, "top10_ocr.json")
DATE = datetime.now().strftime("%Y%m%d")
OUT_TREND = os.path.join(HERE, f"爆款趋势规律_{DATE}.md")
OUT_COPY = os.path.join(HERE, f"文案与标题_{DATE}.md")

ACCOUNT = os.environ.get(
    "ACCOUNT_DESC",
    ("账号定位：垂直领域内容创作者，分享①用AI搞学习（知识库/笔记/效率工具）"
     "②转型做产品。受众：该领域学习者、想转行的从业者。调性：真实经历+干货+有温度。"))

OCR_CHAR_LIMIT = 2500  # 每条笔记 OCR 文字截断长度，防 prompt 超时


def build_ocr_map():
    """note_id -> 该条所有内页 OCR 文字（按页序拼接）。"""
    m = {}
    if not os.path.exists(OCR_FILE):
        return m
    with open(OCR_FILE, encoding="utf-8") as f:
        for note in json.load(f):
            pages = []
            for pg in note.get("pages", []):
                t = (pg.get("text") or "").strip()
                if t and t != "[FILE NOT FOUND]":
                    pages.append(t)
            m[note["note_id"]] = pages
    return m


def digest_one(n, ocr_pages):
    """逐条深拆（单条小 prompt，避免大 prompt 超时）。"""
    ocr_text = "\n".join(ocr_pages)[:OCR_CHAR_LIMIT] if ocr_pages else "（无 OCR 文字）"
    prompt = (
        f"你是小红书爆款图文分析专家。下面是「{n['title']}」这条真实爆款的完整素材：\n\n"
        f"- 标题：{n['title']}\n"
        f"- 互动：赞 {n['liked']} / 藏 {n['collected']}\n"
        f"- 账号：{n['nickname']}\n"
        f"- 标签：{n['tags']}\n"
        f"- 正文（摘要）：{(n['desc'] or '')[:400]}\n"
        f"- 内页图片文字（OCR，内容是主体，含表格/清单/路线图等）：\n{ocr_text}\n\n"
        f"请精炼深拆「为什么这条能爆」，输出：\n"
        f"①内容结构（开头钩子→展开→收尾，结合内页OCR判断信息组织）\n"
        f"②情绪/共鸣钩子\n"
        f"③标题套路\n"
        f"④视觉策略（根据内页文字推断版式/形式：表格/路线图/清单/漫画等）\n"
        f"⑤可借鉴点（针对「垂直领域内容创作者」账号）\n"
        f"用 markdown 分点，每点 1-3 行，总计 150-300 字。"
    )
    for attempt in range(2):
        try:
            r = glm.chat([{"role": "user", "content": prompt}], temperature=0.4)
            return glm.reply_text(r).strip()
        except Exception as e:
            print(f"    ⚠️ 第{attempt+1}次失败: {e}", flush=True)
            time.sleep(3)
    return "（深拆失败，GLM 调用异常）"


def extract_rules(deep_text):
    prompt = (
        "下面是 10 条小红书真实爆款的逐条深拆：\n\n" + deep_text + "\n\n"
        "请榨出可复用的「爆款方法论」，分 4 个维度输出（各 3-5 条）：\n"
        "①标题套路 ②内容结构 ③情绪/共鸣设计 ④视觉风格。\n"
        "用 markdown 分点，总长 300-500 字。"
    )
    try:
        r = glm.chat([{"role": "user", "content": prompt}], temperature=0.6)
        return glm.reply_text(r).strip()
    except Exception as e:
        print(f"  ⚠️ 规律提炼失败: {e}", flush=True)
        return "（规律提炼失败）"


def gen_copy(rules_text):
    prompt = (
        f"账号背景：{ACCOUNT}\n\n爆款方法论：\n{rules_text}\n\n"
        "请基于方法论，给这个账号生成 5 条可直接发布的小红书选题。每条含：\n"
        "①标题（一句话，直接可拿去豆包生成封面，不要解释）\n"
        "②正文文案（小红书风格，带emoji、分段、口语化，300-500字）\n"
        "③话题标签（3-5个 #xxx）\n"
        "不要生成图片、不要给生图提示词。用 markdown 分篇输出。"
    )
    try:
        r = glm.chat([{"role": "user", "content": prompt}], temperature=0.8)
        return glm.reply_text(r).strip()
    except Exception as e:
        print(f"  ⚠️ 文案生成失败: {e}", flush=True)
        return "（文案生成失败）"


def main():
    ap = argparse.ArgumentParser(description="基于 OCR 内页文字做大模型深拆")
    ap.add_argument("--no-rules", action="store_true", help="只出深拆，不提炼规律/文案")
    args = ap.parse_args()

    if not os.path.exists(DATA_FILE):
        print(f"ERROR: 找不到 {DATA_FILE}，请先跑 run_baokuan_digest.py")
        sys.exit(1)
    if not os.path.exists(OCR_FILE):
        print(f"ERROR: 找不到 {OCR_FILE}，请先跑 OCR（不要 --skip-ocr）")
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        notes = json.load(f)
    ocr_map = build_ocr_map()
    print(f"=== 大模型深拆：{len(notes)} 条（基于 OCR 内页文字）===", flush=True)

    # 1) 逐条深拆
    deep_items = []
    for n in notes:
        nid = n["note_id"]
        ocr_pages = ocr_map.get(nid, [])
        print(f"  [{n['rank']}/{len(notes)}] {n['title'][:20]} (OCR {len(ocr_pages)}页)", flush=True)
        d = digest_one(n, ocr_pages)
        deep_items.append(
            f"### TOP{n['rank']}｜{n['title']}\n"
            f"- 互动：赞 {n['liked']} / 藏 {n['collected']}｜账号：{n['nickname']}\n"
            f"- 原文：{n['note_url']}\n\n"
            f"{d}"
        )
        time.sleep(1)  # 防限流

    deep_text = "\n\n---\n\n".join(deep_items)
    report = (
        f"# 真实爆款趋势与规律（TOP{len(notes)} 深拆·OCR内页版）\n\n"
        f"> 数据来源：MediaCrawler 真实爬取 + RapidOCR 内页文字\n"
        f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M}｜模型：{glm.LAST_MODEL}\n\n"
        f"## 一、TOP{len(notes)} 爆款逐条深拆（基于真实内页内容）\n\n" + deep_text
    )

    if args.no_rules:
        with open(OUT_TREND, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"✅ 已保存深拆：{OUT_TREND}（--no-rules，未提炼规律/文案）")
        return

    # 2) 规律提炼
    print("  >> 提炼 4 维度爆款方法论 ...", flush=True)
    rules = extract_rules(deep_text)
    time.sleep(1)

    # 3) 文案标题
    print("  >> 生成 5 条选题文案 ...", flush=True)
    copy = gen_copy(rules)
    time.sleep(1)

    report += f"\n\n## 二、爆款方法论（4 维度）\n\n" + rules + "\n"
    with open(OUT_TREND, "w", encoding="utf-8") as f:
        f.write(report)
    with open(OUT_COPY, "w", encoding="utf-8") as f:
        f.write(f"# 文案与标题（基于 OCR 爆款规律，无图）\n\n> {datetime.now():%Y-%m-%d %H:%M}｜模型：{glm.LAST_MODEL}\n\n" + copy)

    print(f"✅ 已保存：{OUT_TREND}")
    print(f"✅ 已保存：{OUT_COPY}")


if __name__ == "__main__":
    main()
