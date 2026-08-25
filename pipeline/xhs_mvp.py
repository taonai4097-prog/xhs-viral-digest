#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 MVP 一键生成器（通用版）
- 输入一个选题/关键词，调用智谱 GLM 一次性产出：
  标题(≤20字) + 钩子 + 正文(图文风) + 话题标签 + 发布建议
  + 封面配图方案 + 3 张内页配图方案（每张含：生图 prompt / 文案台词 / 版式）
- 同时导出 images.json，供生图工具/API 一键批量出图
- 复用 glm_content_gen.py 的 Key 与 chat()（含 GLM-4.7-Flash 限流自动回退 + 弱网重试）

生图 Provider（运营可配，两档）：
  cogview      —— 智谱 cogview-3-flash（复用 ZHIPU_API_KEY，永久免费，出图带小水印）
  pollinations —— 免费免 key 生图网站（image.pollinations.ai，无水印但偶发排队慢）
  切换方式：--provider pollinations 或 .env 里 IMAGE_PROVIDER=pollinations

用法：
  python xhs_mvp.py --topic "你的选题关键词"
  python xhs_mvp.py --from-recommend --limit 1          # 从「今日选题推荐」取选题生成
  python xhs_mvp.py --topic "某主题" --provider pollinations
  python xhs_mvp.py --batch 3          # 从账号内容支柱自动挑 3 个选题
"""
import os, sys, json, re, argparse, time, shutil, base64, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from glm_content_gen import chat, KEY, LAST_MODEL  # noqa

# 生图开关（main 中按 --no_image / --size / --provider 覆盖）
NO_IMAGE = False
IMG_SIZE = "1024x1024"
PROVIDER = os.environ.get("IMAGE_PROVIDER", "cogview")  # cogview | pollinations

# ---------- 账号定位（在 .env 的 ACCOUNT_* 中配置，此处为兜底默认值） ----------
ACCOUNT = {
    "name": os.environ.get("ACCOUNT_NAME", "你的账号昵称"),
    "platform": os.environ.get("ACCOUNT_PLATFORM", "小红书"),
    "persona": os.environ.get("ACCOUNT_PERSONA", "垂直领域内容创作者，有真实经历"),
    "audience": os.environ.get("ACCOUNT_AUDIENCE", "关注该领域的普通用户 / 学习者"),
    "tone": "真实第一人称，有具体数字和亲身经历，有温度、建立信任，不端着",
    "pillars": [
        os.environ.get("PILLAR_1", "领域入门与实践（真实路径）"),
        os.environ.get("PILLAR_2", "工具实测与效率提升"),
        os.environ.get("PILLAR_3", "经验记录与复盘"),
        os.environ.get("PILLAR_4", "专业内容与个人兴趣交叉"),
        os.environ.get("PILLAR_5", "效率工具/知识管理（笔记/工作流/开源）"),
    ],
}

SYSTEM = f"""你是小红书爆款内容策划+资深视觉导演，服务于账号「{ACCOUNT['name']}」（{ACCOUNT['platform']}）。
账号人设：{ACCOUNT['persona']}
目标受众：{ACCOUNT['audience']}
内容调性：{ACCOUNT['tone']}

你必须输出【可直接发布】的小红书图文帖，且严格符合中国大陆平台规范（不违规、不夸大、不制造焦虑）。"""

def build_user_prompt(topic):
    return f"""请基于账号定位，围绕选题《{topic}》产出一篇可直接发布的小红书图文帖，并配套配图方案。
必须严格输出如下 JSON（不要任何多余文字、不要 markdown 代码块包裹）：

{{
  "topic": "{topic}",
  "title": "标题，不超过20个汉字，带钩子/反差/数字感",
  "hook": "正文第一句（钩子，2行内，抓住痛点或抛反差）",
  "body": "正文全文，用\\n分段，口语化、有emoji、有具体数字/经历，5-8段，结尾引导收藏互动",
  "tags": ["#标签1", "#标签2", "#标签3", "#标签4", "#标签5"],
  "publish_tip": "建议发布时间/发布频率/封面标题字一句建议",
  "cover": {{
    "prompt": "英文生图 prompt（小红书封面风格：干净留白、大字标题、清新治愈、高级感、16:9或3:4竖版）",
    "caption": "封面上要打的大字标题（一句，≤12字）",
    "layout": "版式描述（如：左上大字标题+右侧学姐照片+底部小标签）"
  }},
  "inner_images": [
    {{
      "prompt": "英文生图 prompt（第1张内页：信息图/清单风，适合放要点）",
      "caption": "该页要配的文字/要点（1-3行）",
      "layout": "版式描述"
    }},
    {{
      "prompt": "英文生图 prompt（第2张内页）",
      "caption": "该页要配的文字/要点",
      "layout": "版式描述"
    }},
    {{
      "prompt": "英文生图 prompt（第3张内页：学姐真人感/校园场景）",
      "caption": "该页要配的文字/要点",
      "layout": "版式描述"
    }}
  ]
}}

要求：生图 prompt 必须英文、具体、可复现；caption 必须有信息量，能直接当图上文案。"""

def parse_json(text):
    # 去 code fence
    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.I)
    text = re.sub(r"```$", "", text.strip())
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise

# ---------- 生图后端（两档：cogview 智谱免费额度 / pollinations 免费免key） ----------
IMG_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
POLL_URL = "https://image.pollinations.ai/prompt"


def gen_image(prompt, size="1024x1024", retries=3, provider=None, model=None):
    """按 provider 生图，返回 (file_or_url, source_url)。"""
    provider = provider or PROVIDER
    if provider == "pollinations":
        return gen_image_pollinations(prompt, size, retries)
    return gen_image_cogview(prompt, size, retries)


def gen_image_cogview(prompt, size="1024x1024", retries=3):
    """调用智谱 CogView 生图，返回 (图片URL, 图片URL)。免费模型 cogview-3-flash。"""
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
    """调用 pollinations（免费免key）生图，返回 (本地临时文件, 网络URL)。"""
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
    """把图片 URL 下载到本地；若已是本地文件（pollinations），直接拷贝。"""
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
    """对 封面+3内页 四个 prompt 生图并落盘，返回 ({role: local_path}, {role: source_url})。"""
    provider = provider or PROVIDER
    os.makedirs(img_dir, exist_ok=True)
    saved, urls = {}, {}
    # 封面
    f0, u0 = gen_image(imgs.get("cover", {}).get("prompt", ""), size=size)
    cp = os.path.join(img_dir, "cover.png")
    download(f0, cp)
    saved["cover"] = cp
    urls["cover"] = u0
    # 内页
    for i, im in enumerate(imgs.get("inner_images", []), 1):
        f, u = gen_image(im.get("prompt", ""), size=size)
        p = os.path.join(img_dir, f"inner{i}.png")
        download(f, p)
        saved[f"inner{i}"] = p
        urls[f"inner{i}"] = u
    return saved, urls

def load_recommend_topics(limit=0):
    """从「今日选题推荐.xlsx」（飞书决策台产物）读取选题标题。limit=0 表示全部。"""
    from openpyxl import load_workbook
    p = os.path.join(HERE, "今日选题推荐.xlsx")
    if not os.path.exists(p):
        print(f"ERROR: 找不到 {p}，请先跑 pipeline/plan_of_the_day.py 生成今日选题推荐")
        sys.exit(1)
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


def gen_post(topic, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    print(f">> 生成《{topic}》...")
    r = chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(topic)},
    ], temperature=0.85, timeout=120)
    data = parse_json(r["choices"][0]["message"]["content"])

    slug = re.sub(r"[^\w一-鿿]+", "_", topic)[:30]
    md_path = os.path.join(out_dir, f"xhs_{slug}.md")
    json_path = os.path.join(out_dir, f"xhs_{slug}.json")
    img_path = os.path.join(out_dir, f"xhs_{slug}_images.json")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 小红书图文帖 · {ACCOUNT['name']}\n\n")
        f.write(f"> 选题：{data.get('topic','')}  |  模型：{LAST_MODEL}\n\n")
        f.write(f"## 标题\n{data.get('title','')}\n\n")
        f.write(f"## 正文\n{data.get('hook','')}\n\n{data.get('body','')}\n\n")
        f.write("## 话题标签\n" + " ".join(data.get("tags", [])) + "\n\n")
        f.write(f"## 发布建议\n{data.get('publish_tip','')}\n\n")
        f.write("## 配图方案（封面+3内页）\n")
        c = data.get("cover", {})
        f.write(f"- **封面**：{c.get('caption','')} ｜ 版式：{c.get('layout','')}\n  - prompt: {c.get('prompt','')}\n")
        for i, im in enumerate(data.get("inner_images", []), 1):
            f.write(f"- **内页{i}**：{im.get('caption','')} ｜ 版式：{im.get('layout','')}\n  - prompt: {im.get('prompt','')}\n")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(img_path, "w", encoding="utf-8") as f:
        imgs = {"cover": data.get("cover", {}), "inner_images": data.get("inner_images", [])}
        json.dump(imgs, f, ensure_ascii=False, indent=2)

    # ---- 生图（默认开启，可用 --no_image 关闭）----
    image_paths, image_urls = {}, {}
    if not NO_IMAGE:
        print(f"   生图中（{PROVIDER}，共4张）...")
        img_dir = os.path.join(out_dir, "images", slug)
        try:
            image_paths, image_urls = gen_images_for_post(imgs, img_dir, size=IMG_SIZE, provider=PROVIDER)
            # 回写图片本地路径与源URL到 json
            data["_images_local"] = image_paths
            data["_image_urls"] = image_urls
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 在 md 末尾追加图片清单
            with open(md_path, "a", encoding="utf-8") as f:
                f.write("\n## 配图成品（本地路径）\n")
                for role, p in image_paths.items():
                    f.write(f"- **{role}**：`{p}`\n")
            print(f"   配图已保存：images/{slug}/")
        except Exception as e:
            print(f"   ⚠️ 生图失败（文案仍可用）：{e}")

    print(f"   文案已保存：{os.path.basename(md_path)}")
    print(f"   配图prompt已保存：{os.path.basename(img_path)}")
    return data, md_path, img_path

def main():
    global NO_IMAGE, IMG_SIZE, PROVIDER
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", help="指定选题")
    ap.add_argument("--from-recommend", action="store_true", help="从「今日选题推荐」表读取选题（飞书决策台产物）")
    ap.add_argument("--limit", type=int, default=0, help="配合 --from-recommend：最多取前 N 条（0=全部）")
    ap.add_argument("--batch", type=int, default=0, help="从内容支柱自动生成 N 个")
    ap.add_argument("--out_dir", default=os.path.join(HERE, "xhs_posts"))
    ap.add_argument("--no_image", action="store_true", help="只出文案，不生图")
    ap.add_argument("--size", default="1024x1024", help="生图尺寸，如 1024x1024 / 768x1344（竖版）")
    ap.add_argument("--provider", default=None, choices=["cogview", "pollinations"],
                    help="生图后端：cogview(智谱免费) / pollinations(免key免费)。默认 cogview，可用环境变量 IMAGE_PROVIDER 覆盖")
    a = ap.parse_args()
    NO_IMAGE = a.no_image
    IMG_SIZE = a.size
    if a.provider:
        PROVIDER = a.provider
    print(f">> 生图 Provider：{PROVIDER}（{IMG_SIZE}）")

    topics = []
    if a.topic:
        topics = [a.topic]
    elif a.from_recommend:
        topics = load_recommend_topics(a.limit)
        if not topics:
            print("ERROR: 「今日选题推荐」表为空")
            sys.exit(1)
        print(f">> 从今日选题推荐取 {len(topics)} 条选题")
    elif a.batch:
        topics = ACCOUNT["pillars"][:a.batch]
    else:
        topics = [ACCOUNT["pillars"][0]]

    for t in topics:
        gen_post(t, a.out_dir)
        time.sleep(1)
    print("\n小红书 MVP 一键生成完成 ✅（文案 + 配图已落盘到 xhs_posts/）")

if __name__ == "__main__":
    main()
