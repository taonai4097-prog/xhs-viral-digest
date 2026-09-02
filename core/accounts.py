# -*- coding: utf-8 -*-
"""账号即一等公民：品牌锁绑定到账号空间（accounts/<id>/brand.json）

设计（黄金十步 + 用户硬约束「账号无关、数据不出本机、免费优先」）：
- 每个账号一套 brand.json + references/，互不可见 —— 杜绝「串味」（A 号用了 B 号风格）。
- 不指定账号 → AccountError 直接报错退出，绝不默认值兜底（防静默用错品牌锁）。
- 所有品牌数据都在本机 accounts/ 目录，不联网、不外传。

这是 P0 的落地：把「账号」提升为系统一等公民，代码里不再写死任何具体账号。
"""
import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_DIR = os.path.join(ROOT, "accounts")


class AccountError(Exception):
    """未指定账号 / 找不到该账号品牌锁 / 品牌锁缺失必备字段。"""
    pass


def account_dir(account_id):
    """返回账号目录；账号为空则直接 fail-fast。"""
    if not account_id or not str(account_id).strip():
        raise AccountError("必须指定账号（account），不能留空 —— 品牌锁按账号隔离，留空会串味。")
    return os.path.join(ACCOUNTS_DIR, str(account_id).strip())


def ensure_account_dir(account_id):
    """建账号目录 + references/ 子目录，返回账号根目录。"""
    d = account_dir(account_id)
    os.makedirs(os.path.join(d, "references"), exist_ok=True)
    return d


def brand_path(account_id):
    return os.path.join(account_dir(account_id), "brand.json")


def load_brand(account_id):
    """读取账号品牌锁。缺失 → AccountError（fail-fast，不默认兜底）。"""
    p = brand_path(account_id)
    if not os.path.exists(p):
        raise AccountError(
            "找不到账号「%s」的品牌锁：%s\n"
            "→ 请先分析该账号：python pipeline/brand_analyzer.py analyze "
            "--account %s --cover-dir <封面目录> [--corpus <文案语料>]"
            % (account_id, p, account_id)
        )
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_brand(account_id, brand_dict):
    """落盘 brand.json（自动建目录）。返回文件路径。"""
    d = ensure_account_dir(account_id)
    p = os.path.join(d, "brand.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(brand_dict, f, ensure_ascii=False, indent=2)
    return p


def list_accounts():
    """列出已建品牌锁的账号（目录存在且有 brand.json）。"""
    if not os.path.isdir(ACCOUNTS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(ACCOUNTS_DIR)):
        sub = os.path.join(ACCOUNTS_DIR, name)
        if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "brand.json")):
            out.append(name)
    return out
