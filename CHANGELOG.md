# Changelog

本文件记录公开核心的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [SemVer](https://semver.org/)。

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
