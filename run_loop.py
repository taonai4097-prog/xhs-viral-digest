# -*- coding: utf-8 -*-
"""
run_loop.py —— 极光AIGC 小红书运营闭环编排器（企业级 v3 · Open Core 架构）

把方案里的各阶段串成可重复跑的 loop：
  A. 爬取(克制/限速)  → B. 解析归一化  → C. 验证管线  → D. 热度引擎
  → E. 选题池(推荐理由+指数, human-in-the-loop 闸门)  → [人拍板]
  → F. agent 注入成稿(xhs_mvp --inject, 免费 pollinations 生图)
  → G. 推飞书内容流水(可选)  → H. (可选) 推小红书草稿箱(xiaohongshu-mcp)

架构（对照 黄金十步评估_V3_V4 修复）：
  D1/D3 开箱即死：本文件只依赖公开核心 + core 包。私有飞书/爬取脚本通过
        core.di 能力探测，缺失即降级为本地 CSV 模式（core.local_runner），
        绝不 ModuleNotFoundError。clone 下来放一份 CSV 即可跑出热度看板+选题池。
  D2 静默失败：run_step 改 fail-fast（subprocess.run + check + 超时 + 捕获输出），
        任一阶段非零退出立即 sys.exit，运营绝不可能在假状态上拍板。
  D5 测试抓不到：新增 `doctor` 子命令 + .github/workflows/ci.yml，PR 阶段拦截。
  D6 反馈闭环：generate 阶段可选调用 MetricsCollectorPort（草稿箱回收，预留）。

设计要点（用户硬约束）：
  - 不调用 GLM/智谱：文案由 agent（WorkBuddy 自带模型）在 F 阶段注入。
  - 付费工具全替换为免费本地版（千瓜/新红/灰豚 → analytics 本地热度引擎）。
  - 草稿箱(xiaohongshu-mcp) 为免费开源可选阶段；未部署优雅跳过并提示。

用法：
  python run_loop.py doctor                       # 预检（克隆后先跑这个）
  python run_loop.py run                          # A→E，停在选题池人闸
  python run_loop.py run --no-crawl               # 复用已有 CSV
  python run_loop.py run --no-feishu              # 不推飞书（仅本地 xlsx）
  python run_loop.py run --local                  # 强制本地 CSV 模式（无视私有脚本）
  python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json   # F→G
  python run_loop.py generate --inject <json> --draft     # F→G→H(草稿箱)
  python run_loop.py draft --json pipeline/xhs_posts/xhs_<slug>.json        # 仅推草稿箱
"""
import os
import sys
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "pipeline")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import di, local_runner, doctor  # noqa: E402


def run_step(desc, cmd, timeout=900):
    """fail-fast 执行一个子阶段（修复 D2 静默失败）。

    非零退出码 / 超时 / 命令不存在 都立即中止整个 loop，绝不软跑继续。
    """
    print("\n===== %s =====" % desc)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        r = subprocess.run(
            cmd, cwd=ROOT, env=env, timeout=timeout,
            capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        print("  ⏱️ 超时（>%ds），中止。" % timeout, file=sys.stderr)
        sys.exit(124)
    except FileNotFoundError as e:
        print("  ❌ 命令/脚本不存在：%s" % e, file=sys.stderr)
        sys.exit(127)

    if r.returncode != 0:
        if r.stdout:
            print(r.stdout)
        if r.stderr:
            print(r.stderr, file=sys.stderr)
        print("  ❌ 失败（退出码 %d），已中止。" % r.returncode, file=sys.stderr)
        sys.exit(r.returncode)

    if r.stdout:
        print(r.stdout)
    print("  ✅ 完成（退出码 0）")
    return r.returncode


def stage_run(no_crawl, no_feishu, top, force_local):
    print("\n########## LOOP A→E：爬取 → 验证 → 热度 → 选题池（人闸）##########")

    use_private = di.has_private("crawler") and not force_local
    if use_private:
        # 完整模式：含飞书同步
        crawl_cmd = [sys.executable, di.private_path("crawler")]
        if no_crawl:
            crawl_cmd.append("--no-crawl")
        if no_feishu:
            crawl_cmd.append("--no-feishu")
        crawl_cmd += ["--top", str(top)]
        run_step("A-D 爬取/归一化/验证/热度/选题池(飞书同步)", crawl_cmd)
    else:
        # 本地 CSV 模式（克隆即用，无飞书，无私有脚本依赖）
        why = "（--local 强制）" if force_local else "（未检测到私有爬取脚本）"
        print("  ℹ️ 运行本地 CSV 模式%s：结果写本地 xlsx，不推飞书。" % why)
        try:
            summary = local_runner.run(top=top)
        except Exception as e:  # noqa: BLE001
            print("  ❌ 本地模式失败：%s" % e, file=sys.stderr)
            sys.exit(1)
        print("  ✅ 本地模式完成：%d 原始 / %d 打分" % (summary["n_raw"], summary["n_scored"]))
        print("     热度看板：%s" % summary["heat_board"])
        print("     选题池：  %s" % summary["topic_pool"])
        if summary["top"]:
            print("     Top3 选题：")
            for r in summary["top"]:
                print("       %d. %s  (热度指数 %s)" % (r["排名"], r["选题标题"], r["热度指数"]))

    # 人闸：打印选题池，等运营/AI 拍板
    print("\n────────── 人闸（human-in-the-loop）──────────")
    print("打开「选题池.xlsx / 飞书选题池」看每条的【推荐理由 + 热度指数】，说「用第 N 条」。")
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
             [sys.executable, os.path.join(PIPE, "xhs_mvp.py"), "--inject", inject])

    # G 推飞书内容流水（可选：缺失私有脚本则本地产出，不推飞书）
    if di.has_private("feishu_push"):
        run_step("G 推飞书「内容流水」",
                 [sys.executable, di.private_path("feishu_push"), "--json", inject])
    else:
        print("  ℹ️ 未检测到私有飞书推送脚本(push_to_feishu_content.py)，"
              "F 阶段已写出本地 json/md，未推飞书。")

    # H 草稿箱（可选）
    if draft:
        stage_draft(inject)
    return 0


def stage_draft(json_path):
    print("\n########## LOOP H：推小红书草稿箱（本地桥接 .xhs_bridge，免费可选）##########")
    # 桥接地址：优先读 xiaohongshu_mcp.json 的 mcp_url，缺省即本地 bridge(18070)
    mcp_cfg = os.path.join(ROOT, "xiaohongshu_mcp.json")
    mcp_url = "http://localhost:18070"
    if os.path.exists(mcp_cfg):
        try:
            with open(mcp_cfg, encoding="utf-8") as f:
                mcp_url = (json.load(f).get("mcp_url") or mcp_url).rstrip("/")
        except Exception:
            pass

    # 读注入内容，组装草稿负载
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("  ❌ 读取注入 JSON 失败：%s" % e)
        return 1

    title = data.get("title") or data.get("topic") or "未命名笔记"
    content = data.get("body") or data.get("hook") or ""
    tags = data.get("tags") or []
    # 归一化图片：支持 字符串路径 / {path} 对象；跳过不存在或远程 URL。
    # bridge 启动目录与 run_loop 不同，必须传绝对路径，否则桥那一端找不到图。
    raw_imgs = data.get("images") or []
    images = []
    for it in raw_imgs:
        p = it.get("path") if isinstance(it, dict) else it
        if not p or not isinstance(p, str) or p.startswith("http"):
            continue
        if not os.path.isabs(p):
            p = os.path.normpath(os.path.join(ROOT, p))
        if os.path.exists(p):
            images.append(p)
    payload = {"title": title, "content": content, "tags": tags, "images": images}
    print("  草稿负载：title=%s | 正文 %d 字 | tags=%s | images=%d 张"
          % (title, len(content), tags, len(images)))

    # 真推送：POST /api/v1/draft + 重试（与 bridge 契约一致）
    last_err = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                mcp_url + "/api/v1/draft",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            if out.get("success"):
                print("  ✅ 已推草稿箱：%s" % out.get("data"))
                return 0
            if out.get("code") == "NEED_LOGIN":
                print("  🔐 后端要求登录（NEED_LOGIN）。请先扫码登录小红书：")
                print("     cd .xhs_bridge && npm run login   （弹窗→手机扫→自动存登录态）")
                print("     登录后重跑本命令即可真推草稿箱。")
                return 0
            print("  ⚠️ 后端返回非成功：%s" % out)
            return 0
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "ignore")[:300])
        except Exception as e:
            last_err = str(e)
        print("  ↻ 重试 %d/3：%s" % (attempt, last_err))
        time.sleep(2 * attempt)
    print("  ❌ 草稿箱推送失败（3 次重试）：%s" % last_err)
    print("  排查：桥接服务是否启动？（cd .xhs_bridge && node bridge.js）mcp_url 是否填对？")
    return 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑 A→E，停在选题池人闸")
    p_run.add_argument("--no-crawl", action="store_true")
    p_run.add_argument("--no-feishu", action="store_true")
    p_run.add_argument("--local", action="store_true",
                       help="强制本地 CSV 模式（无视私有爬取脚本）")
    p_run.add_argument("--top", type=int, default=10)

    p_gen = sub.add_parser("generate", help="F→G[→H] 成稿+推飞书[+草稿箱]")
    p_gen.add_argument("--inject", required=True)
    p_gen.add_argument("--draft", action="store_true")

    p_draft = sub.add_parser("draft", help="仅推草稿箱")
    p_draft.add_argument("--json", required=True)

    p_doc = sub.add_parser("doctor", help="预检环境/依赖/适配器（CI 用 --ci）")
    p_doc.add_argument("--ci", action="store_true", help="critical 失败则退出码 1")

    args = ap.parse_args()

    if args.cmd == "run":
        stage_run(args.no_crawl, args.no_feishu, args.top, args.local)
    elif args.cmd == "generate":
        stage_generate(args.inject, args.draft)
    elif args.cmd == "draft":
        stage_draft(args.json)
    elif args.cmd == "doctor":
        sys.exit(doctor.run(ci=args.ci))


if __name__ == "__main__":
    main()
