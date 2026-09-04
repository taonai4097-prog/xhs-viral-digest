# 变更说明

## 类型（对应 Conventional Commits）
- [ ] `feat` 新功能
- [ ] `fix` 缺陷修复
- [ ] `chore` 构建/依赖/治理
- [ ] `docs` 文档
- [ ] `refactor` 重构
- [ ] `test` 测试
- [ ] `ci` CI/CD

## 关联 Issue
- 关闭 #

## 自检（CI 会自动跑，合并前需全绿）
- [ ] `python run_loop.py doctor --ci` 通过
- [ ] `python -m pytest tests/ -q` 通过
- [ ] 私有适配器未泄漏账号信息（`.env` / token / cookie 不进仓库）
- [ ] 已按代码审查清单自检：`docs/code_review/checklist.md`（红线 A1-A5 无一违反）

## 影响范围（给 reviewer 与未来全栈开发者的上下文）
<!-- 这次改了什么、为什么、怎么验证 -->

## 测试计划
<!-- 本地如何复现 / 验证 -->
