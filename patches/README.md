# 极光AIGC 对 NanmiCoder/MediaCrawler 的定制补丁（可选）

> 用途：让爬虫行为与本项目 pipeline 对齐。**不应用也能跑**（原版即可爬），应用后：
> ① 默认 `csv` 导出（pipeline 直接读 CSV）
> ② 竞品追踪一次抓 20 条、关评论（更快、不易风控）
> ③ 单条笔记详情偶发解析异常时跳过继续，不再整批崩溃
> ④ 可选手动扫码头（登录态保存后改 HEADLESS=True 无人值守）
>
> ⚠️ 不含任何账号信息；关键词默认占位，请改成你自己的领域词。

## 应用方式（在本仓库根目录 clone MediaCrawler 后）

```bash
# 1) clone 官方原版
git clone https://github.com/NanmiCoder/MediaCrawler.git tools/MediaCrawler
cd tools/MediaCrawler
# 2) 装依赖（见官方 README，Python 3.10+）
pip install -r requirements.txt
# 3) 应用本补丁（从本仓库根目录执行）
git apply ../patches/media_crawler_xhs_tuning.patch
# 4) 按需修改 config/base_config.py 的 KEYWORDS 为你的领域词
```

> 若 `git apply` 报错（版本差异），手动改 3 处即可：见补丁内 diff。

## 补丁内容（3 个文件）
- `config/base_config.py`：KEYWORDS 占位 / 关 CDP / csv 导出 / 20 条 / 关评论 / HEADLESS 注释
- `media_platform/xhs/core.py`：get_note_detail_async_task 加通用异常兜底（跳过单条不崩批次）+ launch 可选 channel="msedge"（用本机 Edge 而非 test chromium，登录态与日常浏览器同源；无 Edge 环境可去掉该行）
