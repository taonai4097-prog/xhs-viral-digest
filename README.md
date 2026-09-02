# 极光AIGC · 小红书运营闭环（Open Core 架构 v3）

企业级小红书竞品分析 + 选题 + 图文成稿闭环。**公开核心克隆即跑，私有账号件缺失自动降级。**

> 设计依据：`research/企业级竞品爬取与选题方案_2026-08-31.md`（付费标杆 + 免费本地替代双轨）。
> 当前架构体检：`research/黄金十步体检_企业级改造_2026-08-31.md` 与 `research/企业级困境解法方案_V3V4红线修复_2026-09-01.md`。

## 架构（Open Core / 六边形）

```
公开核心（本仓库，克隆即用）
  run_loop.py ──编排 A→H，fail-fast，含 doctor 预检
  core/
    di.py         能力探测：私有适配器存在？否则降级本地模式（绝不 ModuleNotFoundError）
    local_runner  本地 CSV 模式：只依赖 analytics/topic_pool，写本地 xlsx
    doctor.py     预检医生：Python/依赖/核心模块/可选适配器/.env/数据，critical 失败=退出1
  pipeline/
    analytics.py  热度引擎 + 验证管线（字段完整性/反刷量/相对表现R/热度分0-100）
    topic_pool.py 选题池（推荐理由 + 热度指数 + 人闸，不调 GLM）
    compliance.py 合规（限速/脱敏/授权留存/自查）
    xhs_mvp.py    成稿（--inject 由 agent 注入，默认 pollinations 免费生图）

私有适配器（.gitignore，含账号信息，克隆后缺失属正常）
  run_competitor_crawl.py  A-D + 飞书同步（完整）
  sync_to_feishu.py        内容中台同步
  push_to_feishu_content.py 内容流水推送
  → 缺失即降级：run_loop 跑本地 CSV 模式，产出 热度看板.xlsx / 选题池.xlsx
```

## 快速开始（克隆即用）

> 环境：Python 3.10 ~ 3.13（已对 3.13 验证）。

```bash
git clone <你的仓库地址>
cd <仓库目录>

# 1) 装依赖
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) 预检（推荐先跑，CI 也跑这个）
python run_loop.py doctor

# 3) 放一份竞品 CSV（MediaCrawler 导出，或任意含下列列的 csv）
#    列：note_id,title,nickname,liked_count,collected_count,comment_count,share_count,desc,tag_list,note_url,time,source_keyword
#    默认读取 tools/MediaCrawler/data/xhs/csv/search_contents_*.csv

# 4) 跑闭环（停在选题池人闸，你拍板）
python run_loop.py run --local        # 强制本地 CSV 模式（无视私有脚本）
python run_loop.py run                # 有私有脚本则走完整飞书模式
```

## 闭环阶段

```
A 爬取(克制/限速) → B 归一化 → C 验证(反刷量) → D 热度引擎
  → E 选题池(推荐理由+热度指数，human-in-the-loop 人闸) → [你拍板]
  → F agent 注入成稿(xhs_mvp --inject，pollinations 免费生图)
  → G 推飞书内容流水(可选) → H 推小红书草稿箱(可选, xiaohongshu-mcp)
```

- **人闸（关键）**：E 阶段停住，你打开「选题池」看每条的【推荐理由 + 热度指数】再决定用哪条。
  未拍板绝不生成文案（避免浪费资源）。
- **不调 GLM/智谱**：文案由 agent（WorkBuddy 自带模型）在 F 阶段注入；生图默认 pollinations 免费。
- **草稿箱**：部署 `xiaohongshu-mcp`（vmxmy fork，免费开源）后，`generate --draft` 把文案+图
  推到你小红书 App 草稿箱，你在 App 里最后拍板。部署见 `docs/xiaohongshu-mcp-草稿箱部署指南.md`。

## 命令

```bash
python run_loop.py doctor                       # 预检
python run_loop.py run [--no-crawl] [--no-feishu] [--local] [--top 10]
python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json [--draft]
python run_loop.py draft --json pipeline/xhs_posts/xhs_<slug>.json
```

## 测试

```bash
python -m pytest tests/ -q          # 核心导入 + 本地模式 + doctor 无 critical
python pipeline/analytics.py --csv <竞品csv> --top 20   # 单看热度引擎
python pipeline/topic_pool.py --csv <竞品csv> --top 10  # 单看选题池
```

## CI

`.github/workflows/ci.yml`：PR 阶段跑 `doctor --ci`（critical 失败即拦截「开箱即死」）+ `pytest`。
新增公开模块后，确保其能通过 doctor 与测试再合并。

## 免责声明

本项目仅供学习研究。爬取与使用请遵守小红书平台规则及相关法律法规，尊重他人内容版权。
