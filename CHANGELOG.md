# Changelog

本文件记录公开核心的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [SemVer](https://semver.org/)。

## [1.3.1] - 2026-09-03

### 新增
- **脱敏示范数据 `examples/demo_search_contents.csv`**：12 条虚构"医学生/AI"主题笔记（无真实账号/URL/互动），新手不爬虫也能立即跑通热度引擎与本地闭环。
- **README 标注当前版本**，快速开始与复现指南补示范数据用法。

## [1.3.0] - 2026-09-02

### 新增
- **`allow_text` 文字模式开关**：提示词文字策略由写死「无文字」改为可切换 ——
  默认 `False` 出无文字底图（所有模型通用、最稳，标题后期压）；注入 JSON 顶层写
  `"allow_text": true` 即走允许文字模式（豆包等中文渲染尚可，可在画面压大标题，省去后期压字）。
- **品牌锁冲突词自动剥离**：主体描述含 `dark / dramatic / high contrast / 深色背景 / 黑底 / 暗色背景`
  等中英文冲突色调词时自动剥离并告警，防「四图四色」（V5 红队 P2-1 + 补中文深色表述）。
- 运营提示词卡片新增「文字模式」字段与动态使用步骤，允许文字模式下强制提示人工复核中文清晰度。

### 修复
- `allow_text=True` 时品牌锁负向里的「无文字」与本次意图冲突（提示词自相矛盾）——
  该模式下自动剔除负向约束中的「无文字」，否则真实账号（默认 negative 含无文字）下功能失效。
- `xhs_mvp.py` 生图 API 失败兜底路径调用 `build_operator_card` 漏传 `account` →
  会触发 `AccountError` 崩溃（账号改造遗漏）。

### 向后兼容
- `allow_text` 全链路默认 `False`，`REQUIRED_TOKENS` / `FIXED_SUFFIX` 保留为兼容别名；
  既有调用方不传参 = 行为不变。无新增依赖、无新增环境变量。

## [1.2.0] - 2026-09-02

### 新增
- **账号即一等公民（P0）**：品牌锁绑定 `accounts/<id>/brand.json`，`core/accounts.py` 提供加载/保存/
  账号目录/`AccountError`；代码彻底移除写死的具体账号，「不指定账号 → 直接报错退出」绝不用默认值兜底（防串味）。
- **每号自动分析品牌锁（P1）**：`pipeline/brand_analyzer.py` 自动读该号历史封面/文案，生成本号专属品牌锁：
  - 视觉：纯 numpy K-Means(LAB) 色板提取（`seed=42` 可复现）+ accent 挑选 + 多篇主要色众数投票；
    top-3 高分封面复制到 `accounts/<id>/references/` 作视觉参照。
  - 文案：`voice / tone / preferred_phrases / banned_words（合规护栏）/ style_hint` 风格锁。
- **本地 LLM 抽象（`pipeline/local_llm.py`）**：优先本机 Ollama（`qwen3-vl`，图文输入）；失败自动降级
  离线启发式 —— 全程不联网、不调 GLM/智谱、数据不出本机。
- **写稿约束注入（P2）**：成稿 md 头部写入「本号文案风格锁」区块；运营提示词卡片同步展示文案风格锁。
- `xhs_mvp.py` 新增必填 `--account`（缺号退出码 2 + 明确指引），图提示词/文案口吻按账号隔离。

### 修复
- `build_operator_card` 带封面笔记的 `TypeError`（`brand=` 形参名改动残留）。
- 色板双重 `/255` 导致的 accent 变近黑 bug（`#010101` → 正确强调色）。
- `_lab_to_rgb`/`_kmeans_lab` 空簇时 `IndexError`。
- `save_brand` 的 `_locked` 保护逻辑反了 —— 全局锁 `_locked=true` 现整体保留旧值。
- `brand_block` 读取 `visual` 子块兼容新旧 schema，`negative` 缺省兜底不再 `KeyError`。

### 移除
- `pipeline/brand_kits.example.json`（含写死的「小依依依/极光科技」）—— 被按账号自动分析取代。

## [1.0.0] - 2026-09-01

### 新增
- Open Core 架构：`core/` 公开内核（ports / di / local_runner / doctor），克隆即跑本地 CSV 模式。
- 企业级困境修复（V3/V4 红线）：fail-fast 子进程、能力探测降级、Preflight Doctor 门禁。
- 热度评分（CES 公式）、反刷检测、选题池（人闸）、热度看板。
- CI 工作流（`.github/workflows/ci.yml`）：`doctor --ci` + `pytest` 拦截开箱即死。
- GitHub 长期免密推送（SSH Deploy Key）。
- 企业级治理：PR / Issue 模板、CODEOWNERS、CONTRIBUTING、本文件。

### 修复
- 飞书同步批量写入（100/批 + 退避），解决整跑卡死。
- `score_notes` 返回元组的解包 bug。

### 安全
- 清理 `.git/config` 明文 token；调研文档统一纳入 `research/` 版本管理（替代 `git add -f` 绕过）。
