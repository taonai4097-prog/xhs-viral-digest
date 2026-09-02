# -*- coding: utf-8 -*-
"""本地 LLM 抽象（pipeline/local_llm.py）

设计（用户硬约束：不调 GLM/智谱；只用本地 Ollama qwen3-vl 或离线启发式）：
- ollama_chat()：优先调本机 Ollama（/api/chat，支持图文输入）。
- 任何失败 → 抛 OllamaUnavailable → 调用方降级到 heuristic_*（不联网、零成本）。
- heuristic_visual / heuristic_copy：纯规则兜底，保证「无 Ollama 也能跑出品牌锁」。

数据不出本机：Ollama 默认 http://localhost:11434；启发式路径完全本地。
"""
from __future__ import annotations

import os
import re
import base64
import json
import urllib.request
import urllib.error
from collections import Counter

# 合规护栏：广告法 / 平台规则的通用禁用词（生成文案时强制规避）。
# 文案风格锁会把 banned_words 写进品牌锁，成稿环节展示给运营/模型遵守。
BANNED_TEMPLATES = {
    "medical": ["包治", "根治", "疗效", "100%有效", "无副作用", "最安全", " guaranteed", "治愈率"],
    "baby": ["绝对安全", "最聪明", "第一", "唯一", "必备", " guaranteed"],
    "beauty": ["永久", "一针见效", "逆龄", "最", "第一", "绝对", "100%"],
    "default": ["最", "第一", "唯一", "绝对", "100%", "包治", "根治", " guaranteed"],
}

NEG_DEFAULT = "无文字、无水印、不堆砌元素"


class OllamaUnavailable(Exception):
    """Ollama 未运行 / 调用失败 / 模型缺失。调用方应降级到启发式。"""
    pass


def _hex_to_hsl(hex_color):
    """#RRGGBB -> (h 0-360, s 0-1, l 0-1)。支持无 # 前缀。"""
    h = str(hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        return (0.0, 0.0, 0.5)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return (0.0, 0.0, 0.5)
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return (0.0, 0.0, l)
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        hh = (g - b) / d + (6.0 if g < b else 0.0)
    elif mx == g:
        hh = (b - r) / d + 2.0
    else:
        hh = (r - g) / d + 4.0
    return (hh * 60.0, s, l)


def _img_b64(path):
    """读图片转 JPEG base64（Ollama 多模态输入用）。失败返回 None。"""
    try:
        from PIL import Image
        from io import BytesIO
        im = Image.open(path).convert("RGB")
        buf = BytesIO()
        im.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None


def ollama_chat(model, prompt, images=None):
    """调本机 Ollama /api/chat。失败一律抛 OllamaUnavailable（交由调用方降级）。

    model:   模型名（默认 qwen3-vl）
    prompt:  文本 prompt
    images:  图片路径列表（可选，送多模态）
    """
    base = (os.environ.get("OLLAMA_BASE") or "http://localhost:11434").rstrip("/")
    url = base + "/api/chat"
    content = [{"type": "text", "text": prompt}]
    for im in (images or []):
        b64 = _img_b64(im)
        if b64:
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + b64}})
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "format": "json",
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OllamaUnavailable("Ollama HTTP %s：%s" % (e.code, e.reason))
    except Exception as e:  # noqa: BLE001
        raise OllamaUnavailable("Ollama 不可用：%s" % e)
    return (d.get("message", {}) or {}).get("content", "") or ""


def heuristic_visual(palette_hex):
    """离线兜底：按 accent 色相把视觉归为 warm/cool/neutral 三档。

    返回 {style, lighting, composition, negative}（含 negative，防后续 KeyError）。
    """
    accent = (palette_hex or {}).get("accent") or (palette_hex or {}).get("base") or "#888888"
    h, s, l = _hex_to_hsl(accent)
    if s < 0.15 or l < 0.12 or l > 0.92:
        cat = "neutral"
    elif h < 60 or h >= 300:
        cat = "warm"
    else:
        cat = "cool"

    if cat == "warm":
        return {
            "style": "温暖生活感、柔和奶油调，真实不做作，避免广告感与过度精修",
            "lighting": "柔和自然光从左上打入，轻微暖调高光，无硬光斑",
            "composition": "主体居中偏上占画面 60% 以上，背景简洁不抢戏",
            "negative": NEG_DEFAULT,
        }
    if cat == "cool":
        return {
            "style": "清爽专业感、冷调科技/自然质感，干净利落",
            "lighting": "均匀柔光、冷色调，轻微渐变光晕",
            "composition": "主体居中，顶部三分之一留干净空白给标题",
            "negative": NEG_DEFAULT,
        }
    return {
        "style": "极简中性、低饱和高级感，通用于任何品类",
        "lighting": "柔和漫射光，明暗对比弱",
        "composition": "主体居中或三分法，留白充足",
        "negative": NEG_DEFAULT,
    }


def heuristic_copy(corpus_texts, style_hint=None):
    """离线兜底：从语料推断口吻/基调/偏好句式 + 合规禁用词。"""
    texts = [t for t in (corpus_texts or []) if isinstance(t, str) and t.strip()]
    if not texts:
        return _default_copy(style_hint)
    blob = "\n".join(texts)

    # 第一人称检测（决定口吻）
    first_person = bool(re.search(r"(我|咱们|我们|本人|姐妹|宝子|家人们|兄弟|老铁)", blob[:3000]))

    # 开头句高频（偏好句式）
    openings = []
    for t in texts:
        for line in t.splitlines():
            line = line.strip()
            if line:
                openings.append(line[:24])
                break
    common_open = [w for w, _ in Counter(openings).most_common(6) if w]

    # 高频短词（偏好词）
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", blob)
    top_words = [w for w, _ in Counter(words).most_common(8) if w]

    return {
        "voice": "第一人称亲切口吻" if first_person else "第三人称客观口吻",
        "tone": "轻松分享、像朋友聊天" if first_person else "专业可信、信息密度高",
        "preferred_phrases": (common_open or top_words)[:5],
        "banned_words": list(BANNED_TEMPLATES["default"]),
        "style_hint": style_hint or ("偏口语化、带个人体验" if first_person else "偏干货、列点清晰"),
    }


def _default_copy(style_hint=None):
    return {
        "voice": "第一人称亲切口吻",
        "tone": "轻松分享、像朋友聊天",
        "preferred_phrases": [],
        "banned_words": list(BANNED_TEMPLATES["default"]),
        "style_hint": style_hint or "偏口语化、带个人体验",
    }


def banned_words_for(category="default"):
    """按内容品类取合规禁用词模板（medical/baby/beauty/default）。"""
    return list(BANNED_TEMPLATES.get(category, BANNED_TEMPLATES["default"]))
