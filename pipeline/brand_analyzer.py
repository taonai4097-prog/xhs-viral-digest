# -*- coding: utf-8 -*-
"""品牌风格锁分析器（pipeline/brand_analyzer.py）

每号进来 -> 自动读它自己的历史封面/文案 -> 分析出它自己的「视觉风格 + 文案调性」
-> 生成这一号专属的品牌锁（图提示词不同、文案口吻不同），落盘到 accounts/<id>/brand.json。

设计（用户硬约束）：
- 账号无关：代码里不写死任何具体账号；品牌锁按 accounts/<id>/ 隔离。
- 数据不出本机：色板用纯 numpy K-Means(LAB) 本地算；文案优先本地 Ollama，
  失败自动降级启发式（见 local_llm.py），全程不联网、不调 GLM/智谱。
- 可复现：K-Means 固定 random_state=42、n_init=10。
- _locked 保护：人工确认后 _locked=true，--refresh 才覆盖；细分锁 _visual_locked/_copy_locked。

依赖：numpy + Pillow（已在 requirements.txt / venv）。
"""
from __future__ import annotations

import os
import sys
import json
import glob
import argparse
import shutil
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")
for p in (ROOT, PIPE):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
from PIL import Image

from local_llm import (ollama_chat, OllamaUnavailable, heuristic_visual,
                       heuristic_copy, banned_words_for)
from core import accounts as _accts

NEG_DEFAULT = "无文字、无水印、不堆砌元素"


# ============================================================== 颜色数学
def _rgb_to_lab(rgb):
    """rgb: (N,3) float 0-255 -> (N,3) CIE-Lab（D65）。内部统一做 /255。"""
    rgb = rgb.astype(np.float64) / 255.0
    mask = rgb > 0.04045
    rgb_lin = np.where(mask, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    mat = np.array([[0.4124, 0.3576, 0.1805],
                    [0.2126, 0.7152, 0.0722],
                    [0.0193, 0.1192, 0.9505]])
    xyz = rgb_lin @ mat.T
    xyz[:, 0] /= 0.95047
    xyz[:, 1] /= 1.0
    xyz[:, 2] /= 1.08883
    f = np.where(xyz > 0.008856, np.power(xyz, 1.0 / 3.0), (7.787 * xyz) + 16.0 / 116.0)
    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def _lab_to_rgb(lab):
    """Lab -> (N,3) float 0-255。"""
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    def _inv(t):
        return np.where(t > 0.2068966, t ** 3.0, (t - 16.0 / 116.0) / 7.787)

    xyz = np.stack([_inv(fx), _inv(fy), _inv(fz)], axis=1)
    xyz[:, 0] *= 0.95047
    xyz[:, 1] *= 1.0
    xyz[:, 2] *= 1.08883
    mat = np.array([[3.2406, -1.5372, -0.4986],
                    [-0.9689, 1.8758, 0.0415],
                    [0.0557, -0.2040, 1.0570]])
    rgb_lin = xyz @ mat.T
    mask = rgb_lin > 0.0031308
    rgb = np.where(mask, 1.045 * np.power(rgb_lin, 1.0 / 2.4) - 0.055, 12.92 * rgb_lin)
    return np.clip(rgb, 0, 1) * 255.0


def _cdist(a, b):
    """平方欧氏距离矩阵 (n,k)。"""
    a2 = np.sum(a * a, axis=1)[:, None]
    b2 = np.sum(b * b, axis=1)[None, :]
    return a2 + b2 - 2.0 * (a @ b.T)


def _kmeans_lab(feat, k, seed=42, n_init=10, max_iter=100):
    """纯 numpy K-Means（LAB 空间，感知聚类）。返回 (centroids_lab, labels)。"""
    rng = np.random.RandomState(seed)
    n = feat.shape[0]
    best = None
    best_inertia = np.inf
    for _ in range(n_init):
        idx = rng.choice(n, size=k, replace=False)
        centroids = feat[idx].copy()
        labels = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            d = _cdist(feat, centroids)
            labels = np.argmin(d, axis=1)
            new_c = np.empty_like(centroids)
            for j in range(k):
                if np.any(labels == j):
                    new_c[j] = feat[labels == j].mean(axis=0)
                else:
                    new_c[j] = feat[rng.randint(n)].copy()
            if np.allclose(new_c, centroids):
                centroids = new_c
                break
            centroids = new_c
        inertia = float(np.sum(np.min(_cdist(feat, centroids), axis=1) ** 2))
        if inertia < best_inertia:
            best_inertia = inertia
            best = (centroids.copy(), labels.copy())
    return best


def extract_palette(image_path, k=6, resize_to=200, min_distance=40):
    """从一张封面提取色板。返回 (centers_rgb, counts)。

    centers_rgb: [(r,g,b), ...]（按出现频次降序）；counts: 对齐的像素占比计数。
    已过滤近黑/近白、并按 RGB 欧氏距离去重（min_distance）。
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    scale = resize_to / float(max(w, h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh))
    arr = np.asarray(img, dtype=np.float64).reshape(-1, 3)  # 0-255，不在此除 /255

    lab = _rgb_to_lab(arr)
    centroids_lab, labels = _kmeans_lab(lab, k, seed=42, n_init=10)
    centers_rgb = _lab_to_rgb(centroids_lab)  # (k,3) 0-255
    counts = np.bincount(labels, minlength=k).astype(int)

    order = np.argsort(-counts)
    centers_rgb = centers_rgb[order]
    centroids_lab = centroids_lab[order]
    counts = counts[order]

    # 过滤近黑 (L<12) / 近白 (L>96)
    Ls = centroids_lab[:, 0]
    keep = (Ls >= 12) & (Ls <= 96)
    centers_rgb, counts = centers_rgb[keep], counts[keep]

    # 按 RGB 欧氏距离去重（避免几乎同色占多坑）
    final_rgb, final_cnt = [], []
    for c, cnt in zip(centers_rgb, counts):
        if all(np.linalg.norm(c - f) > min_distance for f in final_rgb):
            final_rgb.append(c)
            final_cnt.append(int(cnt))
    final_rgb = [tuple(int(x) for x in c) for c in final_rgb]
    return final_rgb, final_cnt


def _rgb_to_hsl(rgb):
    r, g, b = rgb.astype(np.float64) / 255.0
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


def pick_accent(centers_rgb, counts):
    """按 饱和度*0.7 + 占比*0.3 选强调色（排除近黑/近白/低饱和）。"""
    best, best_score = None, -1.0
    mx = max(counts) if counts else 1
    for (r, g, b), c in zip(centers_rgb, counts):
        h, s, l = _rgb_to_hsl(np.array([r, g, b]))
        if l < 12 or l > 96 or s < 0.1:
            continue
        score = s * 0.7 + (c / mx) * 0.3
        if score > best_score:
            best_score, best = score, (r, g, b)
    if best is None:
        return tuple(int(x) for x in (centers_rgb[0] if len(centers_rgb) else (136, 136, 136)))
    return best


def _main_hex(centers_rgb, counts):
    base = "#%02X%02X%02X" % centers_rgb[0]
    accent = "#%02X%02X%02X" % pick_accent(centers_rgb, counts)
    neutral, best_l = base, -1.0
    for (r, g, b) in centers_rgb:
        _, _, l = _rgb_to_hsl(np.array([r, g, b]))
        if l > best_l:
            best_l, neutral = l, "#%02X%02X%02X" % (r, g, b)
    return {"base": base, "accent": accent, "neutral": neutral}


def _vote_palette(mains):
    """多篇主色众数投票 -> base/accent/neutral + 简单置信度。"""
    base = Counter(m["base"] for m in mains if m.get("base")).most_common(1)
    accent = Counter(m["accent"] for m in mains if m.get("accent")).most_common(1)
    neutral = Counter(m["neutral"] for m in mains if m.get("neutral")).most_common(1)
    return {
        "base": (base[0][0] if base else "#EDEDED"),
        "accent": (accent[0][0] if accent else "#4A90D9"),
        "neutral": (neutral[0][0] if neutral else "#888888"),
    }


def _palette_text(ph):
    return "主底 %s + 强调 %s + 中性 %s" % (ph["base"], ph["accent"], ph["neutral"])


# ============================================================== 语料/输入
def _list_images(directory):
    if not directory or not os.path.isdir(directory):
        return []
    exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.PNG")
    files = []
    for e in exts:
        files += glob.glob(os.path.join(directory, e))
    return sorted(files)


def _img_likes(path, notes):
    """从 notes JSON 里按文件名匹配点赞数（用于选 top-3 参考图）。无则 0。"""
    if not notes:
        return 0
    name = os.path.basename(path)
    for n in notes:
        cov = n.get("cover") or n.get("image") or ""
        if os.path.basename(str(cov)) == name:
            return int(n.get("likes") or 0)
    return 0


def _load_corpus(path):
    """读语料：文件直接读；目录读全部 .txt/.md。按空行切成多条 note 正文。"""
    texts = []
    targets = []
    if path and os.path.isdir(path):
        for e in ("*.txt", "*.md"):
            targets += glob.glob(os.path.join(path, e))
    elif path and os.path.isfile(path):
        targets = [path]
    for f in targets:
        try:
            with open(f, encoding="utf-8") as fh:
                txt = fh.read()
        except Exception:
            continue
        for block in txt.split("\n\n"):
            block = block.strip()
            if block:
                texts.append(block)
    return texts


# ============================================================== 分析
def analyze_visual(account_id, cover_dir, notes=None):
    """分析该号视觉风格：提色板 -> 启发式描述 -> 选 top-3 参考图落盘。"""
    imgs = _list_images(cover_dir)
    if not imgs:
        raise ValueError("cover_dir 无图片：%s" % cover_dir)

    mains = []
    refs = []
    for im in imgs:
        centers, counts = extract_palette(im)
        if not centers:
            continue
        ph = _main_hex(centers, counts)
        mains.append(ph)
        refs.append((im, _img_likes(im, notes)))

    palette_hex = _vote_palette(mains)
    v = heuristic_visual(palette_hex)
    visual = {
        "palette": _palette_text(palette_hex),
        "palette_hex": palette_hex,
        "style": v["style"],
        "lighting": v["lighting"],
        "composition": v["composition"],
        "negative": v["negative"],
    }

    # 参考图：按点赞排序取 top-3（无 likes 则按文件顺序）
    refs.sort(key=lambda x: x[1], reverse=True)
    top3 = [x[0] for x in refs[:3]]
    saved = _copy_references(account_id, top3)

    return {
        "visual": visual,
        "reference_images": saved,
        "_confidence": round(len(imgs) / max(1, len(imgs)), 3),
    }


def _copy_references(account_id, paths):
    d = _accts.ensure_account_dir(account_id)
    ref_dir = os.path.join(d, "references")
    saved = []
    for i, p in enumerate(paths, 1):
        if not os.path.exists(p):
            continue
        dst = os.path.join(ref_dir, "%d_%s" % (i, os.path.basename(p)))
        try:
            shutil.copy(p, dst)
            saved.append("references/" + os.path.basename(dst))
        except Exception:
            continue
    return saved


def analyze_copy(account_id, corpus_texts, style_hint=None, category="default"):
    """分析文案调性：优先 Ollama，失败降级启发式。返回 (copy_dict, generated_by)。"""
    model = os.environ.get("BRAND_LLM_MODEL") or "qwen3-vl"
    try:
        prompt = (
            "你是社媒文案风格分析师。根据下面若干条历史笔记正文，"
            "用 JSON 返回该账号的文案风格锁，字段：\n"
            "voice(口吻) / tone(基调) / preferred_phrases(3-5个偏好句式) / "
            "style_hint(一句话风格提示)。只返回 JSON，不要解释。\n\n"
            + "\n\n".join(corpus_texts[:20])
        )
        resp = ollama_chat(model, prompt, images=None)
        parsed = _extract_json(resp)
        if parsed and parsed.get("voice"):
            parsed.setdefault("banned_words", banned_words_for(category))
            parsed.setdefault("style_hint", style_hint or "")
            return parsed, "ollama"
    except (OllamaUnavailable, Exception):
        pass
    return heuristic_copy(corpus_texts, style_hint), "heuristic"


def _extract_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# ============================================================== 组装 / 落盘
def build_brand(account_id, visual, copy, reference_images, label=None, generated_by="heuristic"):
    visual = dict(visual or {})
    visual.setdefault("negative", NEG_DEFAULT)
    return {
        "label": label or account_id,
        "visual": visual,
        "copy": copy or {},
        "reference_images": reference_images or [],
        "_locked": False,
        "_confidence": 0.5,
        "_generated_by": generated_by,
        "_generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def brand_copy_block(copy):
    """把文案风格锁格式化成 markdown 文本（注入成稿 + 运营卡片）。"""
    copy = copy or {}
    lines = [
        f"- 口吻（voice）：{copy.get('voice', '（未分析）')}",
        f"- 基调（tone）：{copy.get('tone', '（未分析）')}",
        f"- 偏好句式：{('、'.join(copy.get('preferred_phrases', []) or []) or '（未分析）')}",
        f"- 禁用词（合规护栏）：{('、'.join(copy.get('banned_words', []) or []) or '（未分析）')}",
        f"- 风格提示：{copy.get('style_hint', '（未分析）')}",
    ]
    return "\n".join(lines)


def save_brand(brand_dict, account_id, refresh=False):
    """落盘品牌锁，带 _locked 保护：全局锁保留全部旧值；细分锁按字段保留。"""
    old = None
    try:
        old = _accts.load_brand(account_id)
    except Exception:
        old = None

    if old:
        # 全局锁（_locked=true）：无论是否 --refresh，全部旧值只读保留。
        if old.get("_locked"):
            print("  [品牌锁] 账号「%s」已整体锁定（_locked=true），保留全部旧值，不覆盖。"
                  % account_id)
            return _accts.brand_path(account_id)
        merged = dict(old)
        if not (old.get("_visual_locked") and not refresh):
            merged["visual"] = brand_dict.get("visual", old.get("visual"))
        if not (old.get("_copy_locked") and not refresh):
            merged["copy"] = brand_dict.get("copy", old.get("copy"))
        merged["reference_images"] = brand_dict.get("reference_images", old.get("reference_images"))
        merged["_generated_by"] = brand_dict.get("_generated_by", old.get("_generated_by"))
        merged["_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        merged["_confidence"] = brand_dict.get("_confidence", old.get("_confidence"))
        brand_dict = merged

    path = _accts.save_brand(account_id, brand_dict)
    return path


def show_brand(account_id):
    """格式化打印账号品牌锁。"""
    b = _accts.load_brand(account_id)
    v = b.get("visual", {})
    c = b.get("copy", {})
    print("\n========== 品牌锁：%s ==========" % account_id)
    print("标签：%s" % b.get("label", account_id))
    print("生成方式：%s @ %s" % (b.get("_generated_by"), b.get("_generated_at")))
    print("锁定：%s" % b.get("_locked"))
    print("\n[视觉]")
    print("  配色：%s" % v.get("palette"))
    print("  风格：%s" % v.get("style"))
    print("  光照：%s" % v.get("lighting"))
    print("  构图：%s" % v.get("composition"))
    print("  负向：%s" % v.get("negative"))
    print("  参考图：%s" % (b.get("reference_images") or []))
    print("\n[文案]")
    print("  口吻：%s" % c.get("voice", "（未分析）"))
    print("  基调：%s" % c.get("tone", "（未分析）"))
    print("  偏好句式：%s" % (c.get("preferred_phrases") or []))
    print("  禁用词：%s" % (c.get("banned_words") or []))
    print("  风格提示：%s" % c.get("style_hint", "（未分析）"))
    print("=====================================\n")


# ============================================================== CLI
def main():
    ap = argparse.ArgumentParser(description="品牌风格锁分析器（每号自动分析视觉+文案）")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("analyze", help="分析某账号的视觉+文案风格锁")
    a.add_argument("--account", required=True, help="账号 ID（决定 accounts/<id>/ 隔离目录）")
    a.add_argument("--cover-dir", required=True, help="该号历史封面图目录")
    a.add_argument("--corpus", default=None, help="文案语料：文件或目录（.txt/.md）")
    a.add_argument("--notes", default=None, help="可选 JSON：[{cover,likes}] 用于选 top-3 参考图")
    a.add_argument("--label", default=None, help="账号展示名（写进 brand.json）")
    a.add_argument("--category", default="default", help="合规禁用词模板：default/medical/baby/beauty")
    a.add_argument("--refresh", action="store_true", help="强制覆盖（忽略 _locked）")

    s = sub.add_parser("show", help="打印某账号品牌锁")
    s.add_argument("--account", required=True)

    args = ap.parse_args()
    if args.cmd == "analyze":
        notes = None
        if args.notes and os.path.exists(args.notes):
            with open(args.notes, encoding="utf-8") as f:
                notes = json.load(f)

        print(">> 分析账号「%s」视觉风格..." % args.account)
        vis = analyze_visual(args.account, args.cover_dir, notes=notes)

        print(">> 分析账号「%s」文案调性..." % args.account)
        corpus = _load_corpus(args.corpus) if args.corpus else []
        copy, by = analyze_copy(args.account, corpus, category=args.category)
        print("   文案分析方式：%s" % by)

        brand = build_brand(args.account, vis["visual"], copy,
                            vis["reference_images"], label=args.label, generated_by=by)
        brand["_confidence"] = vis.get("_confidence", 0.5)
        path = save_brand(brand, args.account, refresh=args.refresh)
        print("✅ 品牌锁已生成：%s" % path)
        show_brand(args.account)

    elif args.cmd == "show":
        show_brand(args.account)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
