# -*- coding: utf-8 -*-
"""core —— 极光AIGC 公开公共内核（Open Core / 六边形架构）

本包只依赖可公开的核心模块（pipeline/analytics、topic_pool、compliance、xhs_mvp），
对「飞书 / MediaCrawler / 小红书草稿箱」等含账号信息的私有件做**能力探测 + 降级**，
保证公开仓库克隆后即可运行「本地 CSV 模式」，绝不因缺失私有脚本而 ModuleNotFoundError。

对应修复：黄金十步评估_V3_V4 的 D1/D3（开箱即死）、D2（静默失败由 run_loop 处理）、
D5（doctor 预检由本包提供）、D6（MetricsCollectorPort 契约预留）。
"""
from core import di, local_runner, doctor, ports, accounts  # noqa: F401

__all__ = ["di", "local_runner", "doctor", "ports", "accounts"]
