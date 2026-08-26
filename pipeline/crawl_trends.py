# -*- coding: utf-8 -*-
"""
crawl_trends.py —— 真实爬取关键词爆款，产出 CSV（不碰飞书 / 不跑旧分析）

对齐账号方向的关键词写在 pipeline/competitor_targets.json。
本脚本只负责「真实爬取」，深拆与出报告交给 digest_competitor.py / llm_digest_ocr.py。

它把 MediaCrawler 的启动逻辑内联在此（不再依赖已删除的外部模块），保持自包含：
  - 读取关键词清单 -> 把关键词/mode 写进 MediaCrawler 配置 -> 运行 MediaCrawler 搜小红书
  - 首次运行会弹浏览器让你扫码登录小红书，之后登录态缓存复用

用法：
  python pipeline/crawl_trends.py                  # 爬全部关键词
  python pipeline/crawl_trends.py --index 0       # 只跑第 1 条（测登录态）
  python pipeline/crawl_trends.py --per-timeout 240
"""
import os
import sys
import re
import json
import shutil
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MC_DIR = os.path.join(ROOT, "tools", "MediaCrawler")
# MediaCrawler 的虚拟环境（setup.bat 会为其建 .venv）或全局 python 二选一：
#   优先用 MediaCrawler 自建的 .venv；没有则退回到当前解释器（假设依赖已装好）
MC_VENV_PY = os.path.join(MC_DIR, ".venv", "Scripts", "python.exe")
BASE_CFG = os.path.join(MC_DIR, "config", "base_config.py")
XHS_CFG = os.path.join(MC_DIR, "config", "xhs_config.py")
DEFAULT_TARGETS = os.path.join(HERE, "competitor_targets.json")


def load_targets(path):
    """读取关键词/竞品清单 JSON，返回 list[dict]。"""
    if not os.path.exists(path):
        print(f"ERROR: 找不到竞品清单 {path}")
        print("       请复制 pipeline/competitor_targets.example.json 为 competitor_targets.json 并填入你的关键词。")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        data = [data]
    # 只允许 search 模式（本流水线仅支持关键词搜索；creator 主页模式已移除）
    for t in data:
        mode = t.get("mode", "search")
        if mode != "search":
            print(f"ERROR: 清单条目「{t.get('name', '?')}」mode={mode} 不受支持，")
            print("       本版本只支持 search 模式（按关键词搜）。请改为：")
            print('       {"name": "...", "mode": "search", "keyword": "你的关键词"}')
            sys.exit(1)
        if not t.get("keyword"):
            print(f"ERROR: 清单条目「{t.get('name', '?')}」缺少 keyword 字段。")
            print("       请确保每条都含 keyword：{\"name\": \"...\", \"mode\": \"search\", \"keyword\": \"...\"}")
            sys.exit(1)
    return data


def _mc_python():
    """返回用于运行 MediaCrawler 的 python 解释器路径。"""
    if os.path.exists(MC_VENV_PY):  # MediaCrawler 自带 venv
        return MC_VENV_PY
    return sys.executable  # 否则用当前解释器（依赖需装在当前环境）


def backup_once(path):
    bak = path + ".bak"
    if not os.path.exists(bak):
        try:
            shutil.copy(path, bak)
            print(f"  [备份] {os.path.basename(path)} -> {os.path.basename(bak)}")
        except OSError as e:
            print(f"  [警告] 备份 {path} 失败：{e}")


def patch_base_config(mode):
    """把 CRAWLER_TYPE 写进 MediaCrawler 的 base_config.py。"""
    if not os.path.exists(BASE_CFG):
        print(f"ERROR: 找不到 MediaCrawler 配置 {BASE_CFG}")
        print("       请先运行 setup.bat 或手动 clone MediaCrawler 到 tools/MediaCrawler")
        sys.exit(1)
    backup_once(BASE_CFG)
    s = open(BASE_CFG, encoding="utf-8").read()
    s = re.sub(r"CRAWLER_TYPE = \([^)]*\)",
               f'CRAWLER_TYPE = (\n    "{mode}"\n)', s, flags=re.S)
    open(BASE_CFG, "w", encoding="utf-8").write(s)


def patch_xhs_config(target):
    """search 模式：把 keyword 写进 MediaCrawler 的 base_config.py 的 KEYWORDS。"""
    if os.path.exists(XHS_CFG) and target.get("mode") == "creator":
        backup_once(XHS_CFG)
    backup_once(BASE_CFG)
    s = open(BASE_CFG, encoding="utf-8").read()
    kw = target["keyword"]
    # 兼容 KEYWORDS = "..." 与 KEYWORDS = ( "...", ) 两种写法
    if 'KEYWORDS = "' in s:
        s = re.sub(r'KEYWORDS = "[^"]*"', f'KEYWORDS = "{kw}"', s)
    elif "KEYWORDS = (" in s:
        s = re.sub(r"KEYWORDS = \([^)]*\)", f'KEYWORDS = (\n    "{kw}"\n)', s, flags=re.S)
    else:
        print(f"  [警告] 未在 {BASE_CFG} 中找到 KEYWORDS 定义，跳过写入（如需爬取请手动配置）。")
        return
    open(BASE_CFG, "w", encoding="utf-8").write(s)


def run_mediacrawler(timeout=None):
    """运行 MediaCrawler 搜索。timeout=None 为手动模式（不限制，等用户扫码）；
    传 timeout（秒）则到时判定登录态失效、优雅退出避免卡死。"""
    print("  >>> 运行 MediaCrawler（search 模式，首次需扫码登录）...")
    cmd = [_mc_python(), "main.py", "--platform", "xhs", "--lt", "qrcode", "--type", "search"]
    if timeout:
        try:
            rc = subprocess.run(cmd, cwd=MC_DIR, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            print("  ⚠️ 登录态失效/超时：MediaCrawler 在限定时间内未拿到数据（需手动扫码）。")
            print("     请运行 `python pipeline/crawl_trends.py`（不带 --per-timeout 会等扫码）刷新登录态。")
            return 2
    else:
        rc = subprocess.call(cmd, cwd=MC_DIR)
    print(f"  <<< MediaCrawler 退出码={rc}")
    return rc


def main():
    ap = argparse.ArgumentParser(description="真实爬取关键词爆款（search 模式，仅图文由下游过滤）")
    ap.add_argument("--index", type=int, default=None,
                    help="只跑第 N 条关键词（0基），用于快速验证登录态")
    ap.add_argument("--per-timeout", type=int, default=None,
                    help="每条关键词爬取超时(秒)；不传则手动模式（等扫码）")
    ap.add_argument("--targets", default=DEFAULT_TARGETS, help="关键词清单 JSON")
    args = ap.parse_args()

    if not os.path.exists(MC_DIR):
        print("ERROR: 找不到 MediaCrawler（tools/MediaCrawler）。")
        print("       请先运行 setup.bat 一键安装，或手动 clone：")
        print("       git clone https://github.com/NanmiCoder/MediaCrawler.git tools/MediaCrawler")
        sys.exit(1)

    targets = load_targets(args.targets)
    if args.index is not None:
        if not 0 <= args.index < len(targets):
            print(f"ERROR: --index {args.index} 越界（共 {len(targets)} 条，0基）")
            sys.exit(1)
        targets = [targets[args.index]]

    print(f"=== 真实爬取 {len(targets)} 条关键词（search 模式）===")
    for i, t in enumerate(targets, 1):
        kw = t.get("keyword")
        print(f"\n[{i}/{len(targets)}] 关键词：{kw}")
        patch_base_config("search")
        patch_xhs_config(t)
        rc = run_mediacrawler(timeout=args.per_timeout)
        if rc == 2:  # 登录失效
            print("ERROR: 登录态失效，爬取中断。请手动跑 `python pipeline/crawl_trends.py` 扫码后重跑。")
            sys.exit(2)

    print("\n=== 爬取结束，CSV 落在 tools/MediaCrawler/data/xhs/csv/ ===")


if __name__ == "__main__":
    main()
