# 贡献指南（CONTRIBUTING）

本仓库采用 **Open Core** 架构：公开核心（`core/` + 分析脚本）可独立运行，飞书 / 小红书 / MediaCrawler 等含账号信息的脚本为私有适配器，故意不提交。

## 分支模型（Trunk-Based 变体）

- `main` 永远保持可发布状态，**禁止直接 push**。
- 所有改动走**短命特性分支**（寿命 < 2 天）：`feat/xxx`、`fix/xxx`、`chore/xxx`。
- 合并方式：**squash merge**，保持 `main` 历史线性、每个 commit 对应一个完整逻辑。

## 提交规范（Conventional Commits）

提交信息格式：`<type>(<scope>): <subject>`

| type | 含义 |
|------|------|
| feat | 新功能 |
| fix | 缺陷修复 |
| chore | 构建 / 依赖 / 治理 |
| docs | 文档 |
| refactor | 重构（无行为变化） |
| test | 测试 |
| ci | CI / 流水线 |
| perf | 性能优化 |
| style | 格式（不影响逻辑） |
| build | 构建系统 |
| revert | 回退 |

示例：`feat(topic-pool): 增加热度看板的人闸确认状态`

## 推送流程（自动化）

本项目的发布由自动化助手完成，标准流程为：

1. 从 `main` 切出特性分支并开发。
2. 提交（遵循上面规范）。
3. 推特性分支 → 开 PR → CI（`doctor` + `pytest`）全绿后 squash 合入 `main`。
4. 发版时打 `vX.Y.Z` tag 并建 GitHub Release。

## 质量门禁

- `main` 已开启**分支保护**：要求 PR + CI（`preflight`）通过才能合入。
- CI 失败（doctor 报开箱即死 / 测试挂）一律阻断合并，先本地修再推。
- 已推送的错误用 `git revert` 回退（不改写共享历史）；未推送才用 `reset` / `--amend`。

## 密钥与隐私红线

- `.env`、token、cookie、个人运营数据 **永不提交**（见 `.gitignore`）。
- 私有适配器（含账号信息）不进公开仓库；克隆后由本地文件或私有子仓库补齐。
- 怀疑有密钥泄露：立即吊销对应凭证，并用 `git filter-repo` 清理历史，不要只删文件。

## 版本与发布

- 语义化版本 `MAJOR.MINOR.PATCH`（`core/ports.py` 契约变更 → MAJOR）。
- 发版打 tag：`git tag -a v1.2.0 -m "..."`，并建 GitHub Release。
