#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可插拔生图 Provider（pipeline/image_provider.py）

设计目标（用户诉求）：「能调用生图 API 就调 API；没有模型/没配 key，就默认只生成
提示词，让运营拿去免费网站（豆包/即梦等）生成图片」。

企业级思路：把「生图能力」从具体模型里抽出来，做成可插拔适配器 + 自动降级链。
模型好不好、有没有，都不影响流水线跑通——最差降级成提示词交付物，而不是报错中断。

Provider 一览
-------------
  auto        默认。探测环境：有可用生图 API -> 用 API；否则降级 prompt_only
  prompt_only 不出图，只落提示词卡片（给运营去免费网站生成）
  openai      OpenAI 兼容 /images/generations（OpenAI、硅基流动、火山方舟等）
  pollinations 免费免 key（效果一般，保留为显式选项，不再是默认）

配置（.env）
------------
  IMAGE_PROVIDER=auto              # auto | prompt_only | openai | pollinations | cogview
  IMAGE_API_KEY=sk-xxx             # openai 用（留空则回退用 LLM_API_KEY）
  IMAGE_API_BASE=https://.../v1    # openai 用
  IMAGE_MODEL=gpt-image-1          # openai 用
  IMAGE_SIZE=1024x1536             # 可选，默认按平台比例推导
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS = ("auto", "prompt_only", "openai", "pollinations")

POLL_URL = "https://image.pollinations.ai/prompt"


# ---------------------------------------------------------------- 尺寸推导
def size_to_api_size(size):
    """
    把 1080x1440 这类像素尺寸推导成图像 API 常支持的档位。
    3:4 -> 1024x1536；9:16 -> 1024x1792；1:1 -> 1024x1024
    """
    try:
        w, h = (str(size).lower().split("x") + ["1024", "1024"])[:2]
        w, h = int(w), int(h)
    except Exception:
        return "1024x1024"
    if w <= 0:
        return "1024x1024"
    ratio = h / w
    if ratio >= 1.6:
        return "1024x1792"
    if ratio >= 1.25:
        return "1024x1536"
    if ratio >= 0.75:
        return "1024x1024"
    return "1536x1024"


# ---------------------------------------------------------------- 能力探测
def _env(*names):
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v and not v.startswith("sk-把你的") and "填在这里" not in v:
            return v
    return ""


def has_openai_image():
    """是否配置了可用的 OpenAI 兼容生图接口。"""
    base = _env("IMAGE_API_BASE")
    if not base:
        return False
    # key 可复用 LLM_API_KEY（多数厂商同一把 key）
    key = _env("IMAGE_API_KEY") or _env("LLM_API_KEY")
    return bool(key)


def resolve_provider(name=None):
    """
    解析最终 provider。auto 的降级顺序：openai -> prompt_only。
    注意：cogview 不参与 auto（本项目不用智谱，且实测 CogView 无权限 401）。
    """
    n = (name or os.environ.get("IMAGE_PROVIDER") or "auto").strip().lower()
    if n in ("auto", "", "none"):
        if has_openai_image():
            return "openai"
        return "prompt_only"
    if n == "pollination":
        n = "pollinations"
    if n not in PROVIDERS:
        # 未知值不硬失败，降级提示词模式
        return "prompt_only"
    return n


def describe(provider=None):
    """给日志用的一句话说明。"""
    p = resolve_provider(provider)
    if p == "openai":
        return f"openai 兼容接口（{_env('IMAGE_API_BASE')} / {_env('IMAGE_MODEL') or 'gpt-image-1'}）"
    if p == "pollinations":
        return "pollinations 免费免 key（效果一般，非默认）"
    return "提示词模式：只出提示词，由运营去豆包/即梦等免费网站生成"


# ---------------------------------------------------------------- 各 provider 实现
def gen_prompt_only(prompt, size="1024x1536", retries=3):
    """不出图。返回 (None, None)，由调用方改出提示词卡片。"""
    return (None, None)


def gen_openai(prompt, size="1024x1536", retries=3):
    """OpenAI 兼容 /images/generations。返回 (本地文件或URL, 来源URL)。"""
    key = _env("IMAGE_API_KEY") or _env("LLM_API_KEY")
    base = _env("IMAGE_API_BASE").rstrip("/")
    model = _env("IMAGE_MODEL") or "gpt-image-1"
    url = f"{base}/images/generations"
    api_size = _env("IMAGE_SIZE") or size_to_api_size(size)
    payload = {"model": model, "prompt": prompt, "n": 1, "size": api_size}
    data = json.dumps(payload).encode()
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode())
            item = (d.get("data") or [{}])[0]
            if item.get("url"):
                return (item["url"], item["url"])
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
                tmp = os.path.join(os.environ.get("TEMP", "."),
                                   f"gen_{int(time.time())}_{i}.png")
                with open(tmp, "wb") as f:
                    f.write(raw)
                return (tmp, "(b64_json 本地落盘)")
            last = d
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            last = f"HTTP {e.code}: {body}"
            # 401/403 是配置错误，重试无意义，直接抛
            if e.code in (401, 403):
                break
        except Exception as e:
            last = e
        time.sleep(3)
    raise RuntimeError(f"OpenAI 兼容生图失败（已重试{retries}次）：{last}")


def gen_pollinations(prompt, size="1024x1536", retries=3):
    """免费免 key。效果一般，保留为显式选项。"""
    w, h = (str(size).lower().split("x") + ["1024", "1536"])[:2]
    url = f"{POLL_URL}/{urllib.parse.quote(prompt)}?width={w}&height={h}&nologo=true"
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) > 5000 and data[:2] in (b"\xff\xd8", b"\x89P"):
                tmp = os.path.join(os.environ.get("TEMP", "."),
                                   f"poll_{int(time.time())}_{i}.png")
                with open(tmp, "wb") as f:
                    f.write(data)
                return (tmp, url)
            last = f"响应过小或非图片（{len(data)}字节）"
        except Exception as e:
            last = e
        time.sleep(5)
    raise RuntimeError(f"Pollinations 生图失败（已重试{retries}次）：{last}")


_GENS = {
    "prompt_only": gen_prompt_only,
    "openai": gen_openai,
    "pollinations": gen_pollinations,
}


def generate(prompt, size="1024x1536", provider=None, retries=3):
    """
    统一入口。返回 (file_or_url, source_url)；
    prompt_only 模式返回 (None, None)，调用方应改出提示词卡片。
    """
    p = resolve_provider(provider)
    return _GENS[p](prompt, size=size, retries=retries)


def self_check():
    """自检：不联网，只验证降级链与尺寸推导。"""
    return {
        "resolved_default": resolve_provider(None),
        "resolved_explicit_openai": resolve_provider("openai"),
        "resolved_unknown_falls_back": resolve_provider("不存在的provider"),
        "size_3x4": size_to_api_size("1080x1440"),
        "size_9x16": size_to_api_size("1080x1920"),
        "size_1x1": size_to_api_size("1080x1080"),
        "prompt_only_returns_none": generate("测试", provider="prompt_only") == (None, None),
    }


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))
    print("当前生效 provider：", describe())
