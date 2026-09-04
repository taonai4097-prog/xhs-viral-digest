# Changelog

本文件记录公开核心的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [SemVer](https://semver.org/)。

## [1.3.6] - 2026-09-04

### 变更（代码审查机制建立，治理）
- **新增 [代码审查标准与流程](docs/code_review/README.md)**：两级审查模型（L1 机器闸：
  commitlint + doctor + pytest；L2 审查闸：checklist 五维 + 五红线一票否决）、改动分级
  （🟢轻/🟡中/🔴重）、🔴🟡💭 统一结论格式、P# 问题编号闭环。
- **新增 [代码审查清单模板](docs/code_review/checklist.md)**：审查时复制勾选，红线
  A1-A5（demo 不当数据跑 / 凭证不进公开仓 / 品牌锁不静默覆盖 / 账号先行主路不破坏 /
  飞书主键不乱改）一票否决。
- PR 模板自检区补引用 checklist；`.gitignore` 放开 `docs/code_review/` 白名单。
- 历史遗留（上一轮）：本地备份 `backups/`、merge 杂物 `tools/tools_merge_bak/` 纳入
  `.gitignore`，工作树保持干净。

## [1.3.5] - 2026-09-04

### 变更（账号先行主路固化，2026-09-04 用户纠偏）
- **公开文档主路纠偏为「账号先行」**：此前复现指南把主流程写成"爬竞品 → 打分卡选方向"，
  与 2026-09-03 用户固化的真实主路（**先爬自己的账号** → 现象分析 → 主权题口述 → 调研 →
  风格框架 → 打分卡 → 爬爆款 → 选题池 → 内容简报 → 成稿）相反，导致任何新 clone 的 AI
  照文档走就跑偏。
  → `docs/methodology/README.md` 新增「0. 主路唯一：账号先行」总览图 + 各节修正；
    README 快速开始、`首次运行_人闸引导_模板.md` 同步补主路指引。
- **新增 [运营SOP_说人话版](docs/methodology/运营SOP_说人话版.md)**：给不写代码的真人运营，
  每阶段要做什么/在哪拍板/红线（说人话版）。
- **修复方法论文档断链**：`风格分析_*_模板.md` 间互引路径（`docs/` → `docs/methodology/`）、
  打分卡文件名笔误；项目级 skill `xhs-brand-style-workflow` 引用同步对齐。

## [1.3.4] - 2026-09-04

### 变更（demo 红线：主路唯一，2026-09-04 用户拍板）
- **本项目有且只有一条主路：装依赖 → 装爬虫 → 爬真实数据 → run**。
  `examples/demo_search_contents.csv`（12 条虚构"医学生/AI"笔记）**降级为纯【列格式参考】**，
  不再是 run 的合法输入——此前 README 教"cp demo 进 csv 目录跑 run_loop 试跑"，导致
  AI/新手反复拿虚构样本抄近道假装跑通闭环、从没走真实主流程。
- **代码层堵死**：`core/local_runner.py` `find_csvs` 自动 glob **一律排除** `*_demo*.csv`；
  csv 目录**只有 demo** 时 `run` 报错并引导先爬真实数据；显式传 demo 路径同样拒绝。
- **文档层同步**：README「快速开始」、`docs/methodology/README.md`（复现指南）、
  `首次运行_人闸引导_模板.md` 的 demo 段全部改为「仅格式参考、禁止复制进 csv 目录当数据跑」。
- 想单看热度引擎输出格式（不算跑通）仍可：
  `python pipeline/analytics.py --csv examples/demo_search_contents.csv --top 10`。

## [1.3.3] - 2026-09-04

### 修复（黄金十步 V9 红队发现）
- **demo 样本混入真实打分（P2-5）**：本地模式的 `find_csvs` 此前 glob **全收**
  `search_contents_*.csv` 并逐个累加——新手用示范数据跑通后若再放真实爬取 CSV，
  12 条虚构笔记会混进真实选题分析、污染打分。
  → 现在自动 glob 时若目录里**同时存在**真实与 demo 样本（`*_demo*.csv`），demo 会被排除；
    仅当**只有** demo（新手首次试跑引导）才保留放行。README 同步补"跑通后删除 demo"提示。
- **限流自查工具盲区未文档化（P2-6）**：`content_risk_check` 只查文字层（标题/正文/标签），
  封面/图内文字、评论区、图片内容合规不在扫描范围。
  → docstring 补"⚠️ 工具局限"段 + README 闭环 F 步补自查入口与盲区提示（人眼兜底）。

## [1.3.2] - 2026-09-04

### 修复（隔离 clone 体检发现，2026-09-04）
- **demo 示范 CSV 复制后 run_loop 找不到**：README/复现指南原教 `cp examples/demo_search_contents.csv tools/MediaCrawler/data/xhs/csv/`，
  但本地模式只认 `search_contents_*.csv` 前缀 → 复制后文件名不匹配、`run --local` 报"未找到竞品 CSV"。
  → 文档改为复制时重命名：`cp examples/demo_search_contents.csv .../search_contents_demo.csv`。
- **`example.json` 开箱跑 `generate` 必 exit 2**：顶层 `account: "demo"` 指向 `accounts/demo/brand.json`，
  但公开仓库没有该账号（V8 时代遗留，虚构账号实际是 `_example`）→ 新手照 README 试生成即卡死。
  → `example.json` 的 `account` 改为 `_example`，与公开样例账号对齐。
- **样例品牌锁文件名与文档不一致**：README 说样例在 `accounts/_example/brand.json`，实际文件叫 `brand_样例.json`
  → 规范为 `accounts/_example/brand.json`（git mv），文档与文件对齐。
- **首次运行·人闸引导**：AI/新手第一次跑本项目必须阶段化步进、每阶段停下等人确认（见
  `docs/methodology/首次运行_人闸引导_模板.md`），防止"一口气全自动跑完 + 自行写文件"。

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
