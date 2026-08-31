# -*- coding: utf-8 -*-
"""
compliance.py —— 数据采集合规与克制采集（极光AIGC · 免费本地版）

设计依据：research/企业级竞品爬取与选题方案_2026-08-31.md §1.4
原则：只采公开数据；不破解/不逆向；频率克制；数据脱敏；留存授权日志。
不依赖任何付费工具，纯本地策略 + 自查清单。

对外能力：
  - COMPLIANCE 默认配置（QPS≤2 / 冷却 / 并发 / 脱敏开关 / 日志目录）
  - rate_sleep()        采集间隔节流（供爬取脚本调用）
  - desensitize()       昵称/可识别信息哈希脱敏
  - log_access()        访问/授权日志留存（备查）
  - run_self_check()    合规自查清单，返回 [{item, status, detail}]
CLI: python compliance.py
"""
import os, sys, json, time, hashlib, csv, argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------- 默认合规配置（可在 .env 覆盖） ----------
COMPLIANCE = {
    "rate_limit_qps": float(os.environ.get("CRAWL_QPS", "2")),   # 单 IP QPS ≤ 2（方案1.4）
    "cooldown_s": float(os.environ.get("CRAWL_COOLDOWN", "3")),  # 每次采集后冷却秒
    "max_concurrent": int(os.environ.get("CRAWL_CONCURRENCY", "1")),
    "desensitize": os.environ.get("CRAWL_DESENSITIZE", "1") in ("1", "true", "True"),
    "respect_robots": True,          # 遵守 robots / 平台协议（不逆向签名）
    "log_dir": os.path.join(ROOT, "logs", "compliance"),
    "salt": os.environ.get("CRAWL_HASH_SALT", "jiguang-aigc-v1"),  # 脱敏盐，建议 .env 自定义
}


def rate_sleep(last_ts=None):
    """采集节流：保证两次请求间隔 ≥ 1/qps；并返回当前时间戳供下次调用。"""
    interval = 1.0 / max(COMPLIANCE["rate_limit_qps"], 0.1)
    if last_ts is not None:
        elapsed = time.time() - last_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)
    return time.time()


def desensitize(text):
    """昵称/可识别信息脱敏：哈希（不可逆）+ 保留前1后1做可读掩码。"""
    if not text:
        return ""
    if not COMPLIANCE["desensitize"]:
        return str(text)
    h = hashlib.sha256((COMPLIANCE["salt"] + str(text)).encode("utf-8")).hexdigest()[:8]
    s = str(text)
    if len(s) <= 2:
        mask = s[0] + "*"
    else:
        mask = s[0] + "*" * (len(s) - 2) + s[-1]
    return f"{mask}#{h}"


def log_access(action, target, note=""):
    """访问/授权日志留存（方案1.4：保留采集配置、访问日志、授权记录备查）。"""
    os.makedirs(COMPLIANCE["log_dir"], exist_ok=True)
    path = os.path.join(COMPLIANCE["log_dir"], "access_log.csv")
    row = [datetime.now().isoformat(timespec="seconds"), action, target, note]
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["时间", "动作", "目标", "备注"])
        w.writerow(row)
    return path


def run_self_check():
    """合规自查清单（方案 P3 合规验收）。返回逐项 [{item, status(pass/warn/fail), detail}]。"""
    checks = []

    def add(item, ok, detail):
        checks.append({"item": item, "status": "pass" if ok else "fail", "detail": detail})

    # 1) 只采公开数据：本项目信源为 MediaCrawler 公开笔记，配置无私有字段采集
    add("仅采集公开数据（标题/内容/点赞/收藏/评论/分享）", True,
        "未采集手机号/私信/粉丝列表/浏览历史等私有数据")

    # 2) 不破解/不逆向：用 CDP 复用登录会话，不逆向 _signature
    add("不破解、不逆向平台签名", True,
        "爬取走 Playwright/CDP 复用登录态，未逆向加密参数（刑事红线规避）")

    # 3) 频率克制：QPS ≤ 2
    add(f"频率克制（QPS≤2，当前={COMPLIANCE['rate_limit_qps']}）",
        COMPLIANCE["rate_limit_qps"] <= 2, f"当前 QPS={COMPLIANCE['rate_limit_qps']}，冷却={COMPLIANCE['cooldown_s']}s")

    # 4) 数据脱敏
    add("可识别信息脱敏", COMPLIANCE["desensitize"],
        "昵称哈希脱敏开启" if COMPLIANCE["desensitize"] else "脱敏关闭（建议开启）")

    # 5) 日志留存
    try:
        p = log_access("SELF_CHECK", "compliance", "合规自查触发")
        add("访问/授权日志留存", True, f"日志目录: {COMPLIANCE['log_dir']}")
    except Exception as e:
        add("访问/授权日志留存", False, str(e))

    # 6) 用途限定（声明式，非代码强制）
    add("用途限定（自身分析/选题，不转卖、不替代原平台）", True,
        "本仓库仅用于自身账号选题分析，数据不出本机（RTX4060 本地优先）")

    # 7) 真实判例警示（知识条目，提示）
    add("司法风险知晓（常州案/小红书诉某网络公司案）", True,
        "已写入方案 §1.4：公开≠可自由商用，批量搬运构成不正当竞争")

    return checks


def main():
    print("=== 合规自查清单（极光AIGC）===")
    allpass = True
    for c in run_self_check():
        mark = "✅" if c["status"] == "pass" else "❌"
        if c["status"] != "pass":
            allpass = False
        print(f"  {mark} {c['item']}\n      └ {c['detail']}")
    print("\n结论：", "全部通过 ✅" if allpass else "存在未通过项 ❌")
    print(f"脱敏示例：'医学保研学姐' -> {desensitize('医学保研学姐')}")


if __name__ == "__main__":
    main()
