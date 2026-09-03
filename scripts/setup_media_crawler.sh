#!/usr/bin/env bash
# ============================================================
# 极光AIGC · 一键拉取并配置 MediaCrawler（对齐本仓库 pipeline）
# 作用：clone 官方原版 NanmiCoder/MediaCrawler → tools/MediaCrawler
#       → 自动应用 patches/media_crawler_xhs_tuning.patch
# 用法：bash scripts/setup_media_crawler.sh
# 前提：能访问 github.com（国内环境请先开代理/VPN）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MC_DIR="$ROOT/tools/MediaCrawler"
MC_REPO="https://github.com/NanmiCoder/MediaCrawler.git"
PATCH="$ROOT/patches/media_crawler_xhs_tuning.patch"

echo "==> 极光AIGC setup_media_crawler"
echo "    目标目录: $MC_DIR"

# 1) clone（已存在则跳过）
if [ -d "$MC_DIR/.git" ]; then
  echo "==> tools/MediaCrawler 已存在，跳过 clone"
else
  echo "==> clone MediaCrawler 官方原版"
  echo "    $MC_REPO"
  mkdir -p "$(dirname "$MC_DIR")"
  git clone --depth 1 "$MC_REPO" "$MC_DIR"
fi

# 2) 应用对齐补丁
echo "==> 应用极光AIGC 对齐补丁"
if git -C "$MC_DIR" apply --check "$PATCH" 2>/dev/null; then
  git -C "$MC_DIR" apply "$PATCH"
  echo "==> ✓ 补丁已应用"
else
  echo "==> ⚠️ 补丁无法直接应用（MediaCrawler 版本可能已更新）"
  echo "    请手动改 2 个文件（差异见 $PATCH / patches/README.md）："
  echo "      - config/base_config.py   : 关 CDP、csv 导出、20条、关评论"
  echo "      - media_platform/xhs/core.py : 单条解析异常跳过（容错）"
fi

# 3) 完成提示
echo ""
echo "✅ MediaCrawler 就绪。接下来："
echo "  1) 装依赖：cd tools/MediaCrawler && pip install -r requirements.txt"
echo "     （首次跑需下载浏览器：playwright install chromium，约 150MB，请保持联网）"
echo "  2) 改关键词：编辑 tools/MediaCrawler/config/base_config.py 的 KEYWORDS 为你的领域词"
echo "  3) 登录：按 MediaCrawler 官方 README 启动一次搜索扫码登录（登录态保存后免登）"
echo "  4) 回本仓库根目录，把爬到的 CSV 放入 tools/MediaCrawler/data/xhs/csv/"
echo "  5) 跑 pipeline：python pipeline/analytics.py --csv tools/MediaCrawler/data/xhs/csv/search_contents_*.csv --top 20"
echo ""
echo "完整复现流程见：docs/methodology/00_快速复现_端到端指南.md"
