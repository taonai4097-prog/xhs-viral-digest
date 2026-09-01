# -*- coding: utf-8 -*-
"""core/di.py —— 轻量能力探测 + 适配器解析（修复 D1/D3 开箱即死）

不引入 DI 框架（小团队过度工程）。用 os.path.exists 探测可选私有脚本是否存在：
- 存在 → 走完整模式（含飞书同步）
- 缺失 → 核心降级为本地 CSV 模式（core.local_runner），绝不抛 ModuleNotFoundError

私有脚本清单对应 .gitignore 的「含个人账号信息的脚本」段，克隆后缺失属正常。
"""
import os
import sys
from typing import Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "pipeline")

# 私有适配器脚本（被 .gitignore 排除，含账号信息；克隆后缺失属正常）
PRIVATE_SCRIPTS = {
    "crawler": "run_competitor_crawl.py",        # A-D + 飞书同步（完整）
    "feishu_sync": "sync_to_feishu.py",          # 内容中台同步
    "feishu_push": "push_to_feishu_content.py",  # 内容流水推送
    "topic_planner": "plan_of_the_day.py",       # 旧 GLM 选题（已被 topic_pool 取代，兼容）
}


def private_path(name: str) -> str:
    """返回私有脚本的绝对路径（不保证存在）。"""
    return os.path.join(PIPE, PRIVATE_SCRIPTS[name])


def has_private(name: str) -> bool:
    """探测某私有适配器是否存在（克隆后多为 False）。"""
    return os.path.exists(private_path(name))


def detect_adapters() -> Dict[str, bool]:
    """返回全部私有适配器的就绪状态。"""
    return {k: has_private(k) for k in PRIVATE_SCRIPTS}


def python_executable() -> str:
    return sys.executable
