# 小红书竞品爆款深挖 · 一键流水线

基于 **MediaCrawler 真实爬取 + RapidOCR 内页识别 + 通用大模型深拆** 的小红书竞品爆款分析工具。
输入关键词 → 输出「爆款趋势规律 + 可发布文案标题」，全流程脚本化，支持任意 OpenAI 兼容大模型。

## 功能链路

```
① 爬取竞品(MediaCrawler) → ② 过滤video+TOP10排序+下载全图 → ③ 内页OCR提文字
→ ④ 大模型深拆为什么爆 → ⑤ 提炼4维度方法论 → ⑥ 生成文案+标题
```

- **真实数据**：MediaCrawler 真实访问小红书，按赞+藏排序取 TOP10，绝非编造
- **吃透内页**：RapidOCR 本地提取全部内页文字（对比表/路线图/清单），不是只看封面
- **大模型可选**：默认智谱 GLM，或自填任意 OpenAI 兼容模型（DeepSeek/Kimi/通义/豆包/Ollama）
- **不生成图**：只给标题和文案，封面用豆包等工具按标题自行生成

## 快速开始

> 环境要求：**Python 3.10 ~ 3.13**（已针对 3.13 验证），Git。

### 方式一：一键安装（推荐，Windows）

```bash
git clone <你的仓库地址>
cd <仓库目录>
setup.bat        # 自动：建venv + 装依赖 + 下载MediaCrawler + 生成.env
```

装完只需两步：**填 `.env` 的 API Key + 填 `pipeline/competitor_targets.json` 的关键词**，然后跑命令即可。

### 方式二：手动安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

# 下载爬虫（本项目依赖，开源）
git clone https://github.com/NanmiCoder/MediaCrawler.git tools/MediaCrawler
python -m pip install -r tools/MediaCrawler/requirements.txt
python -m playwright install chromium

# 配置
copy .env.example .env   # Windows；填入你的大模型 API
```

### 3. 冒烟测试（可选，建议发布/首次克隆后跑）

```bash
python pipeline/smoke_test.py   # import 全部模块 + 配置自检，快速抓「装完能不能跑」
```

### 4. 配置关键词

编辑 `pipeline/competitor_targets.json`（示例见 `competitor_targets.example.json`）：

```json
[
  {"name": "关键词1", "mode": "search", "keyword": "你的领域关键词A"},
  {"name": "关键词2", "mode": "search", "keyword": "你的领域关键词B"}
]
```

### 5. 一键跑

```bash
python pipeline/run_baokuan_digest.py --with-llm   # 全流程：爬取→TOP10→OCR→深拆→文案
python pipeline/run_baokuan_digest.py --no-crawl --with-llm   # 不重爬，用已有数据出报告
```

产出（均在 `pipeline/`）：
| 文件 | 内容 |
|------|------|
| `top10_data.json` | 结构化原料（含图片本地路径） |
| `top10_ocr.md` | 全部内页 OCR 文字 |
| `爆款趋势规律_YYYYMMDD.md` | TOP10 逐条深拆 + 4 维度方法论 |
| `文案与标题_YYYYMMDD.md` | 5 条选题（标题+正文+标签，无图） |

## 单独跑某个环节

```bash
python pipeline/crawl_trends.py                    # 只爬取
python pipeline/digest_competitor.py               # TOP10 + 下载图片（数据准备）
python pipeline/ocr_images.py                       # 内页 OCR
python pipeline/llm_digest_ocr.py                   # 大模型深拆 + 文案
```

## 配置大模型（任意 OpenAI 兼容）

在 `.env` 中填这三项即可：

| 厂商 | LLM_BASE_URL | LLM_MODEL |
|------|-------------|-----------|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 本地 Ollama | `http://localhost:11434/v1` | `qwen3:8b` |

## 常见问题

- **爬取失败/登录失效**：手动跑一次 `python pipeline/crawl_trends.py` 扫码刷新登录态
- **大模型限流 429**：脚本内置重试+模型回退，重跑 `llm_digest_ocr.py` 即可
- **OCR 速度**：RapidOCR 本地 ~1.5s/张，73 张约 6 分钟，支持断点续跑

## 免责声明

本项目仅供学习研究。爬取与使用请遵守小红书平台规则及相关法律法规，尊重他人内容版权。
