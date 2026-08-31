#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 MVP 一键成稿 + 生图（极光AIGC · 去 GLM 版）

设计（方案 §3 + 用户硬约束「内容生成不用 GLM/智谱」）：
- 文案/配图方案【由 AI（WorkBuddy 自带模型）注入】，本脚本不调用任何外部 LLM。
- 本脚本职责：① 读入 agent 注入的内容 JSON（--inject）；② 用免费生图后端出图
  （默认 pollinations 免 key；cogview 智谱为可选 legacy，需显式 --provider cogview）；
  ③ 落盘 md + json + 图片；④ 供 push_to_feishu_content.py 推飞书。

⚠️ 配图提示词必须【锚定正文】（用户反馈 Point 4）：agent 注入时，cover/inner_images 的
   prompt 必须对应正文里真实提到的截图/体验/清单/对比，禁止「学姐侧身指着图表」式脱节场景。

内容 JSON 约定（agent 注入）：
{
  "topic": "选题", "title": "标题≤20字", "hook": "钩子",
  "body": "正文（\\n分段）", "tags": ["#a","#b"], "publish_tip": "发布建议",
  "cover": {"prompt": "英文生图prompt(锚定正文)", "caption":"封面上大字", "layout":"版式"},
  "inner_images": [ {"prompt":"...","caption":"...","layout":"..."} x3 ]
}

用法：
  python xhs_mvp.py --inject xhs_posts/xhs_<slug>.json          # 注入内容 + 生图
  python xhs_mvp.py --inject xhs_posts/xhs_<slug>.json --no_image
  python xhs_mvp.py --from-recommend                             # 对今日选题推荐里已注入内容的条目生图
"""
import os, sys, json, re, argparse, time, shutil, base64, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# 生图开关（main 中按 --no_image / --size / --provider 覆盖）
NO_IMAGE = False
IMG_SIZE = "1024x1024"
# 默认免费免 key 生图（智谱 cogview 为可选 legacy，不默认，符合「不用 GLM」硬约束）
PROVIDER = os.environ.get("IMAGE_PROVIDER", "pollinations")  # pollinations | cogview

IMG_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
POLL_URL = "https://image.pollinations.ai/prompt"


def gen_image(prompt, size="1024x1024", retries=3, provider=None):
    """按 provider 生图，返回 (file_or_url, source_url)。"""
    provider = provider or PROVIDER
    if provider == "pollinations":
        return gen_image_pollinations(prompt, size, retries)
    return gen_image_cogview(prompt, size, retries)


def gen_image_cogview(prompt, size="1024x1024", retries=3):
    """调用智谱 CogView 生图（可选 legacy，需 ZHIPU_API_KEY；默认不走此路）。"""
    from glm_content_gen import KEY
    payload = json.dumps({"model": "cogview-3-flash", "prompt": prompt, "n": 1, "size": size}).encode()
    last = None
    for i in range(retries):
        req = urllib.request.Request(IMG_URL, data=payload, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode())
                if "data" in d and d["data"] and "url" in d["data"][0]:
                    u = d["data"][0]["url"]
                    return (u, u)
                last = d
        except Exception as e:
            last = e
            time.sleep(3)
    raise RuntimeError(f"CogView 生图失败（已重试{retries}次）：{last}")


def gen_image_pollinations(prompt, size="1024x1024", retries=3):
    """调用 pollinations（免费免 key）生图，返回 (本地临时文件, 网络URL)。"""
    w, h = (size.split("x") + ["1024", "1024"])[:2]
    url = f"{POLL_URL}/{urllib.parse.quote(prompt)}?width={w}&height={h}&nologo=true"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) > 5000 and data[:2] in (b"\xff\xd8", b"\x89P"):
                tmp = os.path.join(os.environ.get("TEMP", "."), f"poll_{int(time.time())}_{i}.png")
                with open(tmp, "wb") as f:
                    f.write(data)
                return (tmp, url)
            last = f"响应过小或非图片（{len(data)}字节）"
        except Exception as e:
            last = e
            time.sleep(5)
    raise RuntimeError(f"Pollinations 生图失败（已重试{retries}次）：{last}")


def download(url, path, retries=3):
    if not url.startswith(("http://", "https://")):
        shutil.copy(url, path)
        return True
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
            return True
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"下载图片失败：{last}")


def gen_images_for_post(imgs, img_dir, size="1024x1024", provider=None):
    """对 封面+3内页 四个 prompt 生图并落盘。提示词由 agent 注入、锚定正文。"""
    provider = provider or PROVIDER
    os.makedirs(img_dir, exist_ok=True)
    saved, urls = {}, {}
    f0, u0 = gen_image(imgs.get("cover", {}).get("prompt", ""), size=size)
    cp = os.path.join(img_dir, "cover.png")
    download(f0, cp)
    saved["cover"] = cp
    urls["cover"] = u0
    for i, im in enumerate(imgs.get("inner_images", []), 1):
        f, u = gen_image(im.get("prompt", ""), size=size)
        p = os.path.join(img_dir, f"inner{i}.png")
        download(f, p)
        saved[f"inner{i}"] = p
        urls[f"inner{i}"] = u
    return saved, urls


def slugify(topic):
    return re.sub(r"[^\w一-鿿]+", "_", topic)[:30]


def load_recommend_topics(limit=0):
    from openpyxl import load_workbook
    p = os.path.join(HERE, "今日选题推荐.xlsx")
    if not os.path.exists(p):
        return []
    wb = load_workbook(p, data_only=True)
    ws = wb[wb.sheetnames[0]]
    headers = [c.value for c in ws[1]]
    idx = {h: i for i, h in enumerate(headers)}
    topics = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not any(r):
            continue
        t = r[idx["选题标题"]]
        if t:
            topics.append(str(t).strip())
    return topics[:limit] if limit else topics


def gen_post_from_data(data, out_dir, provider=None):
    """agent 已注入完整内容 JSON：生图 + 落盘 md/json/images。"""
    topic = data.get("topic") or data.get("title") or "未命名选题"
    slug = slugify(topic)
    md_path = os.path.join(out_dir, f"xhs_{slug}.md")
    json_path = os.path.join(out_dir, f"xhs_{slug}.json")
    img_path = os.path.join(out_dir, f"xhs_{slug}_images.json")
    os.makedirs(out_dir, exist_ok=True)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 小红书图文帖\n\n> 选题：{data.get('topic','')}\n\n")
        f.write(f"## 标题\n{data.get('title','')}\n\n")
        f.write(f"## 正文\n{data.get('hook','')}\n\n{data.get('body','')}\n\n")
        f.write("## 话题标签\n" + " ".join(data.get("tags", [])) + "\n\n")
        f.write(f"## 发布建议\n{data.get('publish_tip','')}\n\n")
        f.write("## 配图方案（封面+3内页，提示词锚定正文）\n")
        c = data.get("cover", {})
        f.write(f"- **封面**：{c.get('caption','')} ｜ 版式：{c.get('layout','')}\n  - prompt: {c.get('prompt','')}\n")
        for i, im in enumerate(data.get("inner_images", []), 1):
            f.write(f"- **内页{i}**：{im.get('caption','')} ｜ 版式：{im.get('layout','')}\n  - prompt: {im.get('prompt','')}\n")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(img_path, "w", encoding="utf-8") as f:
        json.dump({"cover": data.get("cover", {}), "inner_images": data.get("inner_images", [])},
                  f, ensure_ascii=False, indent=2)

    image_paths, image_urls = {}, {}
    if not NO_IMAGE:
        print(f"   生图中（{PROVIDER}，共4张）...")
        img_dir = os.path.join(out_dir, "images", slug)
        try:
            image_paths, image_urls = gen_images_for_post(
                {"cover": data.get("cover", {}), "inner_images": data.get("inner_images", [])},
                img_dir, size=IMG_SIZE, provider=provider)
            data["_images_local"] = image_paths
            data["_image_urls"] = image_urls
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            with open(md_path, "a", encoding="utf-8") as f:
                f.write("\n## 配图成品（本地路径）\n")
                for role, p in image_paths.items():
                    f.write(f"- **{role}**：`{p}`\n")
            print(f"   配图已保存：images/{slug}/")
        except Exception as e:
            print(f"   ⚠️ 生图失败（文案仍可用）：{e}")

    print(f"   文案已保存：{os.path.basename(md_path)}")
    return data, md_path, img_path


def main():
    global NO_IMAGE, IMG_SIZE, PROVIDER
    ap = argparse.ArgumentParser()
    ap.add_argument("--inject", help="注入 agent 生成的内容 JSON（必填，内容由 WorkBuddy 模型产出）")
    ap.add_argument("--from-recommend", action="store_true", help="对今日选题推荐里已注入内容的条目生图")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out_dir", default=os.path.join(HERE, "xhs_posts"))
    ap.add_argument("--no_image", action="store_true", help="只出文案，不生图")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--provider", default=None, choices=["cogview", "pollinations"],
                    help="生图后端（默认 pollinations 免key免费；cogview=智谱可选legacy）")
    a = ap.parse_args()
    NO_IMAGE = a.no_image
    IMG_SIZE = a.size
    if a.provider:
        PROVIDER = a.provider
    print(f">> 生图 Provider：{PROVIDER}（{IMG_SIZE}） ｜ 内容来源：agent 注入（--inject）")

    if a.inject:
        if not os.path.exists(a.inject):
            print(f"ERROR: 找不到注入文件 {a.inject}")
            sys.exit(1)
        data = json.load(open(a.inject, encoding="utf-8"))
        gen_post_from_data(data, a.out_dir, provider=PROVIDER)
    elif a.from_recommend:
        topics = load_recommend_topics(a.limit)
        if not topics:
            print("ERROR: 今日选题推荐为空")
            sys.exit(1)
        done = 0
        for t in topics:
            slug = slugify(t)
            jp = os.path.join(a.out_dir, f"xhs_{slug}.json")
            if not os.path.exists(jp):
                print(f"   （跳过）{t[:20]}：未注入内容（请 agent 先 --inject）")
                continue
            data = json.load(open(jp, encoding="utf-8"))
            gen_post_from_data(data, a.out_dir, provider=PROVIDER)
            done += 1
        print(f"\n已为 {done} 条注入内容生成图文 ✅")
    else:
        print("ERROR: 必须 --inject <内容JSON> 或 --from-recommend（本项目内容由 WorkBuddy 模型注入，不调用 GLM）")
        sys.exit(1)

    print("\n小红书成稿+生图完成 ✅（下一步：push_to_feishu_content.py 推飞书；或 xiaohongshu-mcp 推草稿箱）")


if __name__ == "__main__":
    main()
