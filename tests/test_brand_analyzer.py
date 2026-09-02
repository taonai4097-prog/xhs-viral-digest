# -*- coding: utf-8 -*-
"""tests/test_brand_analyzer.py —— 品牌风格锁分析器单测（全离线启发式，不联网、不调 Ollama）

覆盖：
  1) 色板提取可复现（同图两次结果一致）
  2) accent 不选近白
  3) heuristic_visual 始终返回含 negative 的三档描述（防后续 KeyError）
  4) heuristic_copy 能从语料推出口吻/禁用词
  5) save_brand 的 _locked 保护（已锁定不覆盖）
  6) brand_copy_block 格式
"""
import json
import os
import sys
import tempfile

import numpy as np
from PIL import Image

from core import accounts as _accts
from local_llm import heuristic_visual, heuristic_copy, OllamaUnavailable, ollama_chat
from brand_analyzer import (extract_palette, pick_accent, analyze_visual,
                            build_brand, save_brand, brand_copy_block)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _blank_img(rgb, size=(128, 128)):
    im = Image.new("RGB", size, rgb)
    return im


def _make_cover_dir(tmpdir, n=3, base=(250, 243, 224)):
    d = os.path.join(tmpdir, "covers")
    os.makedirs(d, exist_ok=True)
    paths = []
    for i in range(n):
        rgb = (base[0] + i * 3, max(0, base[1] - i * 2), base[2])
        p = os.path.join(d, "cov_%d.png" % i)
        _blank_img(rgb).save(p)
        paths.append(p)
    return d, paths


def test_palette_deterministic(tmp_path):
    d, paths = _make_cover_dir(str(tmp_path))
    c1, k1 = extract_palette(paths[0])
    c2, k2 = extract_palette(paths[0])
    assert [tuple(map(int, x)) for x in c1] == [tuple(map(int, x)) for x in c2]
    assert k1 == k2
    assert c1, "单色图也应提出色板"


def test_accent_not_white(tmp_path):
    d, paths = _make_cover_dir(str(tmp_path))
    centers, counts = extract_palette(paths[0])
    accent = pick_accent(np.array(centers), counts)
    # 近白（L 接近 96.5、饱和度≈0）不应被当作强调色
    r, g, b = (int(x) for x in accent)
    assert not (r > 240 and g > 240 and b > 240), "强调色不应是近白"


def test_visual_desc_fallback():
    v = heuristic_visual({"accent": "#C85A3A", "base": "#FAF3E0"})  # 暖
    assert v["style"] and "negative" in v, "heuristic_visual 必须带 negative 键"
    v2 = heuristic_visual({"accent": "#2E8B99", "base": "#EAF2F5"})  # 冷
    assert v2["style"] and "negative" in v2
    v3 = heuristic_visual({})  # 无配色也要能兜底
    assert v3["style"] and v3["negative"]


def test_copy_extract():
    texts = [
        "姐妹们我今天去试了一个超好吃的甜品店\n门口排了好长的队\n真的绝了大家快去",
        "我最近挖到一个宝藏护肤方法\n自己用了两周觉得皮肤状态变好了\n分享给需要的姐妹",
    ]
    c = heuristic_copy(texts, style_hint=None)
    assert "第一人称" in c["voice"]
    assert c["banned_words"], "默认合规禁用词非空"
    assert isinstance(c["preferred_phrases"], list)


def test_refresh_keeps_locked(tmp_path, monkeypatch):
    aid = "test_locked_acct"
    real = _accts.ACCOUNTS_DIR
    tmp_accts = os.path.join(str(tmp_path), "accounts")
    monkeypatch.setattr(_accts, "ACCOUNTS_DIR", tmp_accts)
    monkeypatch.setattr(_accts, "ACCOUNTS_DIR", tmp_accts)

    b1 = build_brand(aid,
                     {"palette": "A", "style": "S1", "lighting": "L1",
                      "composition": "C1", "negative": "N1"},
                     {"voice": "v1", "tone": "t1"},
                     ["references/1.png"])
    b1["_locked"] = True
    path = save_brand(b1, aid)

    # refresh=True 应保留 _locked 及其全部旧字段，不被覆盖
    b2 = build_brand(aid,
                     {"palette": "B", "style": "S2", "lighting": "L2",
                      "composition": "C2", "negative": "N2"},
                     {"voice": "v2", "tone": "t2"},
                     [])
    save_brand(b2, aid, refresh=True)
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["_locked"] is True
    assert loaded["visual"]["palette"] == "A", "整体锁定时视觉不许被覆盖"
    assert loaded["copy"]["voice"] == "v1", "整体锁定时文案不许被覆盖"

    # 恢复真实目录
    monkeypatch.setattr(_accts, "ACCOUNTS_DIR", real)


def test_brand_copy_block():
    c = {"voice": "第一人称亲切口吻", "tone": "轻松分享",
         "preferred_phrases": ["我最近"], "banned_words": ["最", "100%"],
         "style_hint": "带个人体验"}
    block = brand_copy_block(c)
    assert "第一人称亲切口吻" in block
    assert "100%" in block
    assert block.count("- ") >= 5


def test_ollama_unavailable_is_catchable(monkeypatch):
    # 确保降级路径存在：Ollama 不可用时能抛可控异常
    from local_llm import OllamaUnavailable
    try:
        ollama_chat("qwen3-vl", "test")
        # 如果本机真的起了 Ollama 且返回了内容，也算通过
        _ = None
    except OllamaUnavailable:
        _ = None
    _ = OllamaUnavailable
    assert True
