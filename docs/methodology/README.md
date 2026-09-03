# 快速复现 · 端到端指南（从零跑到成稿）

> 目标：让任何人 clone 本仓库后，跑通「竞品/账号数据 → 热度验证 → 选题 → 风格分析 → 成稿」完整闭环。
> 本指南是 README「快速开始」的**完整版**：补齐数据从哪来、风格方法怎么用、产出长什么样。
> 环境：Windows / macOS / Linux + Python 3.10~3.13。国内网络请先开代理（clone/pip/浏览器下载都需要）。

---

## 0. 总览（一次跑通要经历什么）

```
[数据获取]  setup_media_crawler.sh ──clone MediaCrawler→爬竞品/账号 CSV
     ↓
[热度验证]  pipeline/analytics.py ──反刷量 + 相对R + 热度分0-100（真数据才可用）
     ↓
[选题池]    pipeline/topic_pool.py ──推荐理由 + 热度指数 + 人闸(你拍板)
     ↓
[风格框架]  docs/methodology/ 方法论 ──账号该发什么/什么语气/不踩红线(可选,做内容号才需要)
     ↓
[成稿]      run_loop.py generate --inject <json> ──agent注入文案+配图方案 → 小红书草稿箱/手动发
```

## 1. 数据获取（爬 MediaCrawler）

```bash
# 一键：clone 官方原版 + 应用本仓库对齐补丁
bash scripts/setup_media_crawler.sh

# 装依赖 + 首次浏览器（见脚本输出提示）
cd tools/MediaCrawler
pip install -r requirements.txt
playwright install chromium        # 首次需下载浏览器,约150MB

# 改关键词为你的领域词
#   config/base_config.py → KEYWORDS = "你的领域词1,你的领域词2"
#   CRAWLER_TYPE = "search"（关键词搜索）或 "creator"（指定账号主页）

# 启动一次搜索(首次扫码登录)
python main.py --platform xhs --lt qrcode --type search
```

> 爬完 CSV 落在 `tools/MediaCrawler/data/xhs/csv/search_contents_<日期>.csv`。
> 已有 CSV 可不爬——格式对齐即可（列：note_id,title,nickname,liked_count,collected_count,comment_count,share_count,desc,tag_list,note_url,time,source_keyword）。

## 2. 热度验证（反刷量 + 打分）

```bash
python pipeline/analytics.py --csv tools/MediaCrawler/data/xhs/csv/search_contents_*.csv --top 20
```

输出：热度分 0-100（CES 0.7 + 增速 0.3）、相对表现 R、反刷量风险（评论率<0.5% 高赞 / 收藏赞>3 / R>50x 会标人工复核）。
**反刷量不过的数据不要当选题依据。**

## 3. 选题池（人闸拍板）

```bash
python pipeline/topic_pool.py --csv tools/MediaCrawler/data/xhs/csv/search_contents_*.csv --top 10
```

产出候选选题（推荐理由 + 热度指数）。**由你拍板选哪条**，工具不替你决定发什么。

## 4. 风格分析（可选，做内容号/个人 IP 才需要）

如果账号要**持续发内容**，先定风格（发什么方向/什么语气/不踩什么红线）：

1. 跑方法论文档（都在 `docs/methodology/`）：
   - `风格分析_双轨流水线SOP_模板.md` — 总流程：客观调研轨(读者/赛道/爆款) ∩ 主观口述轨(你想干嘛) → 风格框架
   - `风格分析_问题库_用户问卷_模板.md` — 你回答的主观部分（个人版/企业版）
   - `风格分析_调研包模板_模板.md` — Agent 帮你查的客观部分
   - `选题方向选择打分卡_模板.md` — 该爬哪个方向（候选池≥10 → 一票否决红线 → 加权打分）
2. 产出样例见 `accounts/_example/`（虚构账号 xiaoya 的风格框架/内容简报/brand.json 长什么样）

## 5. 成稿（注入内容 → 出文案+配图方案）

```bash
# agent 已写好内容 JSON（标题/正文/标签/配图提示词, 见 pipeline/xhs_posts/*.json 结构）
python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json        # 出成稿 md + 配图提示词
python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json --draft # 出稿后推小红书草稿箱
```

- 文案由 agent（模型）注入生成，本仓库核心不调外部 LLM；生图默认免费 pollinations，也可自配 API。
- 发稿人闸：草稿箱（App 里最后看一眼）或手动复制文案+图到 App。

## 6. 约定与红线（重要）

- 标题 ≤20 字（小红书截断）；正文 ≤1000 字；图 ≤18 张 / 单张 ≤10MB
- 医疗/健康类内容遵守平台规则：不称医生给诊疗建议、不推医疗产品、不站外导流（详见各账号 brand.json 的 compliance）
- 爬虫/发文注意频率，避免被判 spam

## 常见问题

| 现象 | 解决 |
|---|---|
| clone / 下载慢或失败 | 国内开代理/VPN 后重试 |
| MediaCrawler 扫码失败 | 首次把 HEADLESS 关掉（config/base_config.py）用可见窗口扫码 |
| 补丁 apply 失败 | MediaCrawler 版本更新了，手动改 2 个文件（见 patches/README.md） |
| 爬到的数据反刷量风险高 | 降低频率/换时段重爬；别用刷量数据选题 |
| 成稿标题超长 | 标题 ≤20 字是硬限制，agent 注入时已校验，手动改时注意 |
