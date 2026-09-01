# -*- coding: utf-8 -*-
"""core/ports.py —— 端口契约（Ports & Adapters / 六边形架构）

定义系统对外部依赖的抽象接口。公开核心只依赖这些契约，
具体实现（飞书多维表格 / MediaCrawler 爬虫 / 小红书草稿箱 / 效果回收）
作为**可选适配器**在 private/ 提供（被 .gitignore 排除）。

这样：公开仓库克隆后，缺失私有适配器不会崩 —— 核心降级为本地 CSV 模式。
新增一个渠道（如抖音、微博）只需实现对应 Port，不改核心编排。
"""
from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class CrawlerPort(Protocol):
    """竞品爬取 + 解析 + 验证 + 热度 + 选题池 的完整阶段（A→E）。"""

    def run(self, top: int = 10, no_crawl: bool = False, no_feishu: bool = False) -> None:
        ...


@runtime_checkable
class ContentStorePort(Protocol):
    """内容中台（飞书多维表格等）同步。"""

    def sync_competitor(self) -> None:
        ...

    def sync_topic_pool(self) -> None:
        ...

    def sync_heat_board(self) -> None:
        ...

    def push_content(self, inject_json: str) -> None:
        ...


@runtime_checkable
class DraftPublisherPort(Protocol):
    """把成稿推到小红书草稿箱（人工最后拍板）。"""

    def save_draft(self, content: Dict[str, Any]) -> str:
        ...


@runtime_checkable
class MetricsCollectorPort(Protocol):
    """回收已发笔记的真实数据，回灌选题池/热度看板（H→A 反馈闭环）。"""

    def collect(self) -> None:
        ...
