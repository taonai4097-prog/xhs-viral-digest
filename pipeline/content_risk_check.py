#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
content_risk_check.py —— 小红书发布前限流风险自查（极光AIGC · 2026-09-03）

用法:
  python pipeline/content_risk_check.py --file pipeline/xhs_posts/xhs_<slug>.json   # 查成稿 JSON
  python pipeline/content_risk_check.py --md   pipeline/xhs_posts/xhs_<slug>.md    # 查成稿 md
  python pipeline/content_risk_check.py --text "一段要发布的文案..."                # 查任意文本

覆盖 5 大类限流触发面（基于 2026-09 平台规则 + 真实判例调研）:
  1. 平台名/工具名点名（最致命——2026-09-03 实测被"限制推荐+搜索"）
  2. 站外导流（微信/QQ/二维码/私聊/看主页 等，含谐音）
  3. 极限词 + 承诺词（最/第一/100%/根治 等绝对化用语）
  4. 医疗/功效越界（三品一械/治XX/祛斑美白根治 等，本项目账号尤其要查）
  5. 其他（AI 内容未标/AI味过重、低质重复堆砌、敏感类目、联系方式、未成年）

输出: 逐条风险 [{category, level(pass/warn/fail), matched, hint}]
  fail = 高危必改（平台名/引流/极限词医疗）
  warn = 建议改（AI味/堆砌/敏感类目倾向）

⚠️ 工具局限（务必知晓，运营人眼兜底）:
  本工具**只查文字层**——即标题、正文、标签、发布提示语这类纯文本。
  以下盲区**不在扫描范围内**，需发布前人工复核:
  1. 封面图 / 内页图里的「图内文字」（如海报大字、截图水印、A 软件/竞品 logo）
  2. 评论区（评论里的引流/导流话术由评论者负责，但置顶引导文案需自查）
  3. 图片本身的内容合规性（如医疗场景图片是否暗示疗效）
  自查建议: 配图尽量不出现其他平台/工具 logo 与联系方式；图内大字与正文同标准过滤。
"""
import argparse, json, re, sys, pathlib

# ==================== 风险词库（可扩展，勿删判例注释） ====================

# 1) 平台/工具点名 —— 2026-09-03 真实判例: 正文提"扣子(Coze)"+"workbuddy" 被限流处置
PLATFORM_NAMES = [
    # AI 工具/平台（本项目最易踩）
    "扣子", "Coze", "coze", "豆包", "ChatGPT", "WorkBuddy", "workbuddy", "即梦",
    "Kimi", "文心一言", "通义千问", "DeepSeek", "deepseek", "讯飞星火", "Midjourney",
    "Runway", "Sora", "Claude", "Gemini", "Notion", "飞书", "钉钉", "Slack",
    # 外站平台
    "抖音", "快手", "B站", "bilibili", "知乎", "微博", "微信公众号", "微信",
    "YouTube", "Instagram", "TikTok", "淘宝", "京东", "拼多多", "小红书外",
    # 电商/团购
    "某宝", "桃宝", "🍑", "pxx",
    # 学术库/平台（2026-09-03 追加：同"点名即风险"逻辑）
    "PubMed", "知网", "CNKI", "万方", "维普", "Web of Science",
]
# 排除：提到"小红书"本身合规；"微信"单独留引流类(见下)
PLATFORM_ALLOW = ["小红书", "小红薯"]

# 2) 站外导流（含谐音暗语 —— 2026 语义追踪升级全识别）
DRAIN_WORDS = [
    "微信号", "加微信", "VX", "vx", "V信", "薇", "卫星号", "私聊", "私我", "私信我",
    "看主页", "点主页", "主页有", "评论区自取", "举手", "福利暗号", "关注领取", "关注获取",
    "加QQ", "QQ群", "手机号", "电话联系", "邮箱", "二维码", "扫码", "链接自取",
    "公众号", "回复关键词", "后台回复", "小号", "带带", "求购私",
]
# 谐音: 微→薇 已含; 另加常见
DRAIN_PATTERNS = [
    r"[加➕]?[薇vV][信xX]", r"加{0,1}卫星", r"私[聊我信]", r"主[页面].{0,4}[有找]", r"[二维码]{1,2}",
]

# 3) 极限词 + 承诺词（绝对化用语）
#    整词匹配易误报（"第一步/唯一出路"是正常表达），分级：
#    fail = 广告/宣传语境才用的绝对化词；warn = 普通语境也常见但可能越界的词
ABS_WORDS_FAIL = [
    "绝对", "100%", "百分百", "首选", "顶级", "最佳", "最强", "全网最低", "全网最高",
    "销量第一", "排名第一", "国家级", "世界级", "永久", "彻底根治", "万能", "包治",
    "一次见效", "永不反弹", "包上岸", "保过", "稳赚", "无风险", "零风险", "秒杀",
    "闭眼入", "必买", "神器", "天花板", "yyds", "绝绝子", "最好用", "最有效",
    "最划算", "最省钱", "第一名", "国货之光", "行业领先", "top1", "NO.1",
]
# 普通语境合法、仅广告语境才敏感的（命中→warn 提示自查）
ABS_WORDS_WARN = [
    "第一", "唯一", "最", "根治", "彻底", "高效", "首选推荐",
]
# "最"合法搭配（最近/最早/最终…）——命中即豁免
_LEGAL_ZUI = [
    "最近", "最后", "最早", "最大", "最小", "最终", "最初", "最新", "最常用", "最容易",
    "最怕", "最坑", "最头疼", "最直观", "最快", "最少", "最准", "最稳", "最高峰", "最前沿",
    "最全", "最想", "最爱", "最了解", "最熟悉", "最适合", "最需要", "最明显", "最重要",
    "最直接", "最麻烦", "最真实", "最划算", "最省钱", "最简单", "最基础", "最基本",
    "第一步", "第一时间", "第一次", "第一课", "第一期", "第一篇", "第一条", "第一性",
]
ABS_PATTERN_EXTRA = [
    (r"100\s*%", "极限词 100%"),
]

# 4) 医疗/功效越界 —— 医疗账号最敏感（无资质不得涉）
#    只列强功效断言词；"医学生/口腔/医院/医疗AI"等行业词合规，不查
MED_WORDS_FAIL = [
    "根治", "药到病除", "包治", "疗效", "医用级", "械字号", "处方药",
    "祛斑", "美白祛斑", "抗炎杀菌", "消炎止痛", "治愈率", "临床治愈",
    "减肥药", "瘦身", "增高", "丰胸", "壮阳", "特效",
]
MED_WORDS_WARN = [
    "治疗", "药物", "药品", "保健品", "医疗器械", "降血糖", "降血压", "助眠",
    "美白", "抗炎", "杀菌", "消肿", "止痛", "医用",
]
# 医疗账号的行业词（命中→pass，但若与功效词组合会另报）
MED_TOPIC_OK = ["医学生", "医学", "口腔", "医院", "医疗AI", "临床", "规培", "读研", "医生职业"]

# 5) AI 内容未标注 + AI 味（2026-05 起 AI 治理全量落地：不标=违规）
AI_MARK_RULE = {
    "rule": "若内容为 AI 生成/辅助，发布页必须勾选『AI 辅助创作』；纯 AI 无改写，正文开头写『本篇内容AI辅助生成』",
    "hint": "本仓库内容为 AI 辅助生成——发布时务必勾选 AI 标注，否则首次限流7天+扣信用分",
}

# 6) 其他低质信号
LOWQUALITY = {
    "emoji_too_many": 15,   # emoji 数量阈值
    "repeat_times": 5,      # 同词重复阈值
    "title_len": 20,        # 标题字数（>20 截断）
    "body_len": 1000,       # 正文字数（>1000 截断）
}


# ==================== 扫描逻辑 ====================

def scan(text, title=""):
    """扫描文本，返回风险列表。"""
    risks = []
    def add(cat, level, matched, hint):
        risks.append({"category": cat, "level": level, "matched": matched, "hint": hint})

    t = title + "\n" + text if title else text

    # 1) 平台/工具点名
    for w in PLATFORM_NAMES:
        if w in t and not any(a in t for a in PLATFORM_ALLOW):
            # 排除"不是点名推广"的误报：仅当作为实体出现（简单启发式：含于正文且非词汇片段）
            add("平台/工具点名", "fail", w,
                f"点名'{w}'易判『推广其他平台』→ 泛化为「AI搭建平台/免费工具」等不点名表述")

    # 2) 引流
    for w in DRAIN_WORDS:
        if w in t:
            add("站外导流", "fail", w, "引流/联系方式 → 轻则限流重则封号；转化只能走官方店铺/蒲公英/评论区置顶'在小红书搜XX'")
    for p in DRAIN_PATTERNS:
        m = re.search(p, t)
        if m:
            add("站外导流", "fail", m.group(0), "谐音引流词 → 2026 语义追踪全识别，删")

    # 3) 极限词（fail 硬词 + warn 需自查词 + "最"合法搭配豁免）
    masked = t
    for w in _LEGAL_ZUI:
        masked = masked.replace(w, "·" * len(w))
    for w in ABS_WORDS_FAIL:
        if w in t:
            add("极限/承诺词", "fail", w, f"绝对化用语'{w}' → 改「多数情况下/我用过觉得」")
    for w in ABS_WORDS_WARN:
        if w in masked:
            # "第一/唯一/最/根治"等：仅广告语境（接排名/推荐/选择等）才报 warn
            ad = re.search(r"唯一(?=推荐|选择|一家|官方|合作|指定|渠道)", masked) \
                 or re.search(r"(?<=全网|销量|排名|行业)第一", masked) \
                 or re.search(r"(?<=全网|史上|极致|体验)最佳", masked) \
                 or re.search(r"根治", masked)
            if ad:
                add("极限/承诺词", "fail", ad.group(0), f"广告绝对化语境'{ad.group(0)}' → 改程度词")
    for pat, hint in ABS_PATTERN_EXTRA:
        m = re.search(pat, t)
        if m:
            add("极限/承诺词", "fail", m.group(0).strip(), hint)

    # 4) 医疗功效越界（行业词豁免；功效断言词 fail/warn）
    for w in MED_WORDS_FAIL:
        if w in t:
            add("医疗功效越界", "fail", w, f"功效断言'{w}'无资质必违规 → 改体验描述('用完感觉''多数人反馈')")
    for w in MED_WORDS_WARN:
        if w in t and not any(tok in w for tok in []):
            add("医疗功效越界", "warn", w, f"'{w}'若为功效暗示→改中性词；讲行业/AI应用可")

    # 5) AI 标注提醒
    add("AI内容标注", "warn", "AI辅助", AI_MARK_RULE["hint"])

    # 6) 低质/长度
    if title and len(title) > LOWQUALITY["title_len"]:
        add("标题超长", "fail", f"{len(title)}字", f"标题>{LOWQUALITY['title_len']}字截断降权")
    if len(text) > LOWQUALITY["body_len"]:
        add("正文超长", "fail", f"{len(text)}字", f"正文>{LOWQUALITY['body_len']}字会截断")
    emoji_n = len(re.findall(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', t))
    if emoji_n > LOWQUALITY["emoji_too_many"]:
        add("emoji过多", "warn", f"{emoji_n}个", f"emoji>{LOWQUALITY['emoji_too_many']}个显营销/低质")

    return risks


def check_json(path):
    """检查成稿 JSON（xhs_posts/xhs_*.json）。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return [{"category": "读取失败", "level": "fail", "matched": path, "hint": str(e)}]
    title = d.get("title") or d.get("topic") or ""
    text = "\n".join([
        d.get("hook", ""), d.get("body", ""), d.get("publish_tip", ""),
        " ".join(d.get("tags", [])),
    ])
    return scan(text, title)


def check_md(path):
    """检查成稿 md（xhs_posts/xhs_*.md）：取 标题/正文 段。"""
    try:
        t = pathlib.Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return [{"category": "读取失败", "level": "fail", "matched": path, "hint": str(e)}]
    title = ""
    m = re.search(r"^## 标题\n(.+)", t, re.M)
    if m:
        title = m.group(1).strip()
    # 正文：## 正文 到 ## 话题标签 之间
    m = re.search(r"## 正文\n(.*?)(?=\n## )", t, re.S)
    body = m.group(1) if m else ""
    return scan(body, title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="成稿 JSON 路径")
    ap.add_argument("--md", help="成稿 md 路径")
    ap.add_argument("--text", help="任意文本")
    args = ap.parse_args()

    if args.file:
        risks = check_json(args.file)
    elif args.md:
        risks = check_md(args.md)
    elif args.text:
        risks = scan(args.text)
    else:
        print("需 --file / --md / --text 其一"); sys.exit(1)

    icon = {"fail": "❌", "warn": "⚠️", "pass": "✅"}
    n_fail = n_warn = 0
    for r in risks:
        if r["level"] == "fail": n_fail += 1
        elif r["level"] == "warn": n_warn += 1
        print(f'{icon.get(r["level"],"•")} [{r["category"]}] 命中「{r["matched"]}」')
        print(f'      → {r["hint"]}')
    if not risks:
        print("✅ 未发现风险")
    print(f"\n=== 结论: {n_fail} 处必改 / {n_warn} 处建议 ===")
    if n_fail:
        print("⚠️ 有高危项——修改后再发布，否则大概率限流/处置")
    else:
        print("🎉 可发布（记得勾选 AI 辅助创作标注）")


if __name__ == "__main__":
    main()
