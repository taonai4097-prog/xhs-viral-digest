# -*- coding: utf-8 -*-
"""
digest_competitor.py —— 深拆真实爆款 TOP10，出趋势规律 + 文案标题（无图）

读取 tools/MediaCrawler/data/xhs/csv/search_contents_*.csv（真实爬取），
仅保留本账号方向关键词、仅图文（过滤 video），按互动数取 TOP10，
下载封面图 -> 视觉理解（智谱GLM-4V，失败则由平台模型/人工补）-> 阅读完整正文 -> 逐条深拆 ->
榨规律 -> 给「垂直领域创作者」账号生成文案+标题（无图无提示词）。

用法：
  python pipeline/digest_competitor.py
  python pipeline/digest_competitor.py --limit 10
"""
import os, sys, csv, json, base64, io, re, time, argparse, urllib.request, urllib.error
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import glm_content_gen as glm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MC_CSV_DIR = os.path.join(ROOT, "tools", "MediaCrawler", "data", "xhs", "csv")
IMG_DIR = os.path.join(ROOT, "pipeline", "crawl_imgs")
TARGETS = json.load(open(os.path.join(ROOT, "pipeline", "competitor_targets.json"), encoding="utf-8"))
KEYWORDS = [t["keyword"] for t in TARGETS]


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
        sys.exit(1)
    for fn in os.listdir(MC_CSV_DIR):
        if not fn.startswith("search_contents_") or not fn.endswith(".csv"):
            continue
        fp = os.path.join(MC_CSV_DIR, fn)
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                kw = (r.get("source_keyword") or "").strip()
                if kw not in KEYWORDS:
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
    """下载一条笔记的全部图片，按 note_id 分目录存储，返回 [(序号, 本地路径)]。"""
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


def vision_understand(img_path, prompt):
    try:
        from PIL import Image
        im = Image.open(img_path).convert("RGB")
        im.thumbnail((768, 768))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"    [图处理失败] {e}")
        return None
    for m in ["glm-4v-plus", "glm-4v-flash", "glm-4v"]:
        payload = json.dumps({
            "model": m,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt}
            ]}]
        }).encode("utf-8")
        req = urllib.request.Request(glm.URL, data=payload, headers={
            "Authorization": f"Bearer {glm.KEY}",
            "Content-Type": "application/json"
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return None


def deep_digest(top):
    print("  >> 视觉理解 TOP 封面（智谱 GLM-4V，失败则标注）...")
    for i, r in enumerate(top, 1):
        imgs = download_all_images(r)
        img = imgs[0][1] if imgs else None
        vis = None
        if img:
            vis = vision_understand(img, "这是小红书一篇爆款图文笔记的封面图。请用50字内描述：版式（大字标题/拼图/截图/真人出镜/纯插画）、配色风格、是否有人物、文字占比、整体情绪感。")
        r["_visual"] = vis or "（视觉理解不可用，需人工看原帖）"
        print(f"    [{i}/{len(top)}] {(r.get('title') or '')[:18]} -> {'✓视觉' if vis else '✗视觉'}")
        time.sleep(1)
    print("  >> GLM 逐条深拆为什么爆...")
    items = []
    for r in top:
        items.append(
            f"【{r.get('note_id')}】标题：{r.get('title')}\n"
            f"互动：赞{r['_liked']}/藏{r['_collected']} 账号：{r.get('nickname')}\n"
            f"标签：{r.get('tag_list')}\n"
            f"正文：{(r.get('desc') or '')[:600]}\n"
            f"封面视觉：{r['_visual']}\n"
            f"链接：{r.get('note_url')}"
        )
    prompt = ("下面是小红书真实爆款图文笔记（已按互动数排序 TOP10），每条含标题/互动/标签/正文/封面视觉/链接。\n\n"
              + "\n---\n".join(items)
              + "\n\n请逐条深度拆解「为什么这条能爆」，每条给：①内容结构（开头钩子→展开→收尾）②情绪/共鸣钩子 ③标题套路 ④视觉策略 ⑤可借鉴点。用 markdown 分点，务必保留每条的原文链接。")
    return glm.reply_text(glm.chat([{"role": "user", "content": prompt}], temperature=0.4)), items


def extract_rules(deep_text):
    prompt = ("基于上面10条爆款拆解，请你榨出可复用的「爆款方法论」，分4个维度输出（各3-5条）：\n"
              "①标题套路 ②内容结构 ③情绪/共鸣设计 ④视觉风格。\n"
              "用 markdown。")
    return glm.reply_text(glm.chat([{"role": "user", "content": deep_text + "\n\n" + prompt}], temperature=0.6))


def gen_copy(rules_text):
    account = os.environ.get(
        "ACCOUNT_DESC",
        ("账号定位：垂直领域内容创作者，分享①用AI搞学习（知识库/笔记/效率工具）"
         "②转型做产品。受众：该领域学习者、想转行的从业者。调性：真实经历+干货+有温度。"))
    prompt = (f"账号背景：{account}\n\n爆款方法论：\n{rules_text}\n\n"
              "请基于方法论，给这个账号生成 5 条可直接发布的小红书选题。每条含：\n"
              "①标题（一句话，直接可拿去豆包生成封面，不要解释）\n"
              "②正文文案（小红书风格，带emoji、分段、口语化，300-500字）\n"
              "③话题标签（3-5个 #xxx）\n"
              "不要生成图片、不要给生图提示词。用 markdown 分篇输出。")
    return glm.reply_text(glm.chat([{"role": "user", "content": prompt}], temperature=0.8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--prepare-only", action="store_true",
                    help="只做数据准备：过滤→TOP10→下载封面→导出结构化原料JSON，不调任何模型（深拆交给平台大模型）")
    args = ap.parse_args()
    os.makedirs(IMG_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    print("=== 真实爆款深拆 ===")
    rows = load_notes()
    if not rows:
        print("ERROR: 没有命中关键词的笔记，请先跑 crawl_trends.py")
        sys.exit(1)
    top = top_n(rows, args.limit)
    print(f"  TOP{len(top)} 已选出")
    if args.prepare_only:
        # 下载全部图片（封面+内页）+ 导出结构化原料，认知深拆交给 WorkBuddy 平台多模态模型
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
        print("   下一步：由 WorkBuddy 平台多模态模型读全部图片+正文做深拆")
        return
    deep_text, _ = deep_digest(top)
    rules = extract_rules(deep_text)
    copy = gen_copy(rules)
    report = (f"# 真实爆款趋势与规律（TOP{len(top)} 深拆）\n\n"
              f"> 数据来源：MediaCrawler 真实爬取，关键词={KEYWORDS}\n"
              f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M}\n\n"
              f"## 一、TOP{len(top)} 爆款逐条深拆\n\n" + deep_text + "\n\n"
              f"## 二、爆款方法论（4维度）\n\n" + rules + "\n")
    with open(os.path.join(ROOT, "pipeline", f"爆款趋势规律_{date}.md"), "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(ROOT, "pipeline", f"文案与标题_{date}.md"), "w", encoding="utf-8") as f:
        f.write(f"# 文案与标题（基于爆款规律，无图）\n\n> {datetime.now():%Y-%m-%d %H:%M}\n\n" + copy)
    print(f"✅ 已生成：爆款趋势规律_{date}.md / 文案与标题_{date}.md")


if __name__ == "__main__":
    main()
