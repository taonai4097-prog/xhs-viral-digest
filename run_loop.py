# -*- coding: utf-8 -*-
"""
run_loop.py —— 极光AIGC 小红书运营闭环编排器（企业级改造 v2）

把方案里的各阶段串成一条可重复跑的 loop：
  A. 爬取(克制/限速)  → B. 解析归一化  → C. 验证管线  → D. 热度引擎
  → E. 选题池(推荐理由+指数, human-in-the-loop 闸门)  → [人拍板]
  → F. agent 注入成稿(xhs_mvp --inject, 免费 pollinations 生图)
  → G. 推飞书内容流水  → H. (可选) 推小红书草稿箱(xiaohongshu-mcp)

设计要点（对应方案 + 用户硬约束）：
  - 不调用 GLM/智谱：文案由 agent（WorkBuddy 自带模型）在 F 阶段注入；生图默认 pollinations 免费。
  - 付费工具全部替换为免费本地版（千瓜/新红/灰豚 → analytics 本地热度引擎）。
  - 草稿箱(xiaohongshu-mcp) 为免费开源可选阶段；未部署时优雅跳过并提示。

用法：
  python run_loop.py run                 # 跑 A→E，停在「选题池」人闸（运营看推荐理由+指数拍板）
  python run_loop.py run --no-crawl      # 复用已有 CSV
  python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json   # F→G
  python run_loop.py generate --inject <json> --draft     # F→G→H(草稿箱)
  python run_loop.py draft --json pipeline/xhs_posts/xhs_<slug>.json        # 仅推草稿箱
"""
import os, sys, argparse, subprocess, json, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "pipeline")
HERE = PIPE


def run_step(desc, cmd, timeout=900):
    print(f"\n===== {desc} =====")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    rc = subprocess.call(cmd, cwd=ROOT, env=env, timeout=timeout)
    print(f"  (退出码 {rc})")
    return rc


def stage_run(no_crawl, no_feishu, top):
    print("\n########## LOOP A→E：爬取 → 验证 → 热度 → 选题池（人闸）##########")
    # A-D + 竞品爆款库同步：run_competitor_crawl 已内含验证/热度/写库/同步
    crawl_cmd = [sys.executable, os.path.join(PIPE, "run_competitor_crawl.py")]
    if no_crawl:
        crawl_cmd.append("--no-crawl")
    if no_feishu:
        crawl_cmd.append("--no-feishu")
    crawl_cmd += ["--top", str(top)]
    run_step("A-D 爬取/归一化/验证/热度/竞品爆款库+选题池+热度看板", crawl_cmd)
    # 注：run_competitor_crawl 已内含 选题池+热度看板+竞品爆款库 的飞书同步，
    #     无需再调 plan_of_the_day.py（避免重复同步与数据分歧）。

    # 人闸：打印选题池，等运营/AI 拍板
    print("\n────────── 人闸（human-in-the-loop）──────────")
    print("打开飞书「选题池」看每条的【推荐理由 + 热度指数】，说「用第 N 条」。")
    print("AI 据此生成内容（WorkBuddy 模型），写 xhs_posts/xhs_<slug>.json，")
    print("再跑：python run_loop.py generate --inject <该json> [--draft]")
    return 0


def stage_generate(inject, draft):
    print("\n########## LOOP F→G[→H]：成稿 → 推飞书[→草稿箱] ##########")
    if not (inject and os.path.exists(inject)):
        print("ERROR: 需 --inject <agent注入的内容JSON>（文案由 WorkBuddy 模型生成，不调 GLM）")
        return 2
    # F 成稿 + 生图（默认 pollinations 免费）
    run_step("F 成稿 + 生图（pollinations）",
             [sys.executable, os.path.join(PIPE, "xhs_mvp.py"),
              "--inject", inject])
    # G 推飞书内容流水
    run_step("G 推飞书「内容流水」",
             [sys.executable, os.path.join(PIPE, "push_to_feishu_content.py"),
              "--json", inject])
    # H 草稿箱（可选）
    if draft:
        stage_draft(inject)
    return 0


def stage_draft(json_path):
    print("\n########## LOOP H：推小红书草稿箱（xiaohongshu-mcp，免费可选）##########")
    # xiaohongshu-mcp 为免费开源 MCP（Playwright 自动化，本地 cookie）。
    # 部署后这里可调用其 save_draft 工具；未部署则优雅跳过并提示。
    mcp_cfg = os.path.join(ROOT, "xiaohongshu_mcp.json")
    if not os.path.exists(mcp_cfg):
        print("  ⚠️ 未检测到 xiaohongshu-mcp 配置（xiaohongshu_mcp.json）。")
        print("  草稿箱阶段跳过。部署方式（免费）：")
        print("    1) 安装 xiaohongshu-mcp（vmxmy/xiaohongshu-mcp，MIT，Playwright）")
        print("    2) 首次扫码登录，cookie 本地留存")
        print("    3) 在 xiaohongshu_mcp.json 填 mcp 地址，本阶段即调用 save_draft 推草稿箱")
        print("  本期已留接口，部署后即可闭环（呼应方案 Point 6：在小红书 App 里看草稿最后拍板）。")
        return 0
    # 已部署：调用 MCP save_draft（交由 agent/MCP 客户端执行）
    print(f"  ✅ 检测到 {mcp_cfg}，交由 xiaohongshu-mcp 的 save_draft 推送（agent 调用 MCP 工具）。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="跑 A→E，停在选题池人闸")
    p_run.add_argument("--no-crawl", action="store_true")
    p_run.add_argument("--no-feishu", action="store_true")
    p_run.add_argument("--top", type=int, default=10)
    p_gen = sub.add_parser("generate", help="F→G[→H] 成稿+推飞书[+草稿箱]")
    p_gen.add_argument("--inject", required=True)
    p_gen.add_argument("--draft", action="store_true")
    p_draft = sub.add_parser("draft", help="仅推草稿箱")
    p_draft.add_argument("--json", required=True)
    args = ap.parse_args()

    if args.cmd == "run":
        stage_run(args.no_crawl, args.no_feishu, args.top)
    elif args.cmd == "generate":
        stage_generate(args.inject, args.draft)
    elif args.cmd == "draft":
        stage_draft(args.json)


if __name__ == "__main__":
    main()
