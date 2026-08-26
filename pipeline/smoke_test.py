# -*- coding: utf-8 -*-
"""
smoke_test.py —— 冒烟测试：import 全部核心模块 + 配置自检

跑法：python pipeline/smoke_test.py
  该脚本不依赖任何第三方库、不联网、不爬取，纯本地检查，
  用于在发布前快速抓「模块缺失 / 配置冲突 / 依赖缺失」这类裸奔问题。

退出码：0 = 全部通过；非 0 = 有环节失败（详见输出）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

FAILED = []
PASSED = []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"  ✅ {name}")
    except Exception as e:  # noqa: BLE001
        FAILED.append(f"{name}: {e}")
        print(f"  ❌ {name}: {e}")


def _check_modules():
    # 关键：这几个模块必须能 import；任一缺失都是「开箱即死」级缺陷
    import glm_content_gen  # noqa: F401
    import crawl_trends  # noqa: F401
    import digest_competitor  # noqa: F401
    import ocr_images  # noqa: F401
    import llm_digest_ocr  # noqa: F401
    import run_baokuan_digest  # noqa: F401

    # run_baokuan_digest 用的是子进程方式调别的脚本，这里同时验证它引用的路径存在
    for p in [
        os.path.join(HERE, "crawl_trends.py"),
        os.path.join(HERE, "digest_competitor.py"),
        os.path.join(HERE, "ocr_images.py"),
        os.path.join(HERE, "llm_digest_ocr.py"),
    ]:
        assert os.path.exists(p), f"一键入口引用的脚本缺失: {p}"


def _check_placeholder_key():
    # 校验 .env / 环境变量里的 key 不是占位符（避免忘改 key 发真实请求崩脆）
    key = (os.environ.get("LLM_API_KEY") or os.environ.get("ZHIPU_API_KEY") or "").strip()
    placeholder_hits = ["把你的key", "sk-把你的", "your-key", "sk-your", "xxxx", "your_api"]
    if key and any(h in key.lower() for h in placeholder_hits):
        raise AssertionError("检测到占位 API Key（未填写真实 key）。请编辑 .env 填入真实 LLM_API_KEY。")


def _check_requirements():
    req = os.path.join(ROOT, "requirements.txt")
    assert os.path.exists(req), "requirements.txt 缺失"
    with open(req, encoding="utf-8") as f:
        text = f.read()
    assert "rapidocr-onnxruntime" in text, "requirements.txt 缺少 rapidocr-onnxruntime"


def _check_targets_example():
    example = os.path.join(HERE, "competitor_targets.example.json")
    assert os.path.exists(example), "competitor_targets.example.json 缺失"
    import json
    with open(example, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list) and data, "example 应是非空 list"
    for t in data:
        assert t.get("mode") == "search", f"example 条目 {t.get('name')} 应为 search 模式（防 KeyError）"
        assert t.get("keyword"), f"example 条目 {t.get('name')} 缺少 keyword"


def _check_data_consistency():
    # digest_competitor.py 读取 pipeline/top10_data.json（若存在），校验 key 兼容
    dp = os.path.join(HERE, "top10_data.json")
    if os.path.exists(dp):
        import json
        with open(dp, encoding="utf-8") as f:
            notes = json.load(f)
        for n in notes[:1]:
            for k in ("rank", "note_id", "title", "images"):
                assert k in n, f"top10_data.json 条目缺字段 {k}"


if __name__ == "__main__":
    print("=== 冒烟测试：import 全部核心模块 + 配置自检 ===", flush=True)
    check("核心模块 import", _check_modules)
    check("占位 key 自检", _check_placeholder_key)
    check("requirements.txt 自检", _check_requirements)
    check("competitor_targets.example 自检", _check_targets_example)
    check("top10_data.json 一致性", _check_data_consistency)
    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("✅ 全部通过")
