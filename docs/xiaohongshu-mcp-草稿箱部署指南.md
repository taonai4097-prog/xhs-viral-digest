# 小红书草稿箱（xiaohongshu-mcp）部署与接入指南

> 目标：让 `run_loop.py` 在「成稿」之后，把**文案 + 图片自动推到你小红书 App 的草稿箱**，你在 App 里最后看一眼再发布（呼应运营闭环里的「人闸」）。
> 隐私：全程**本机运行**，Cookie 留在你电脑，数据不出本机（符合项目「数据不出本机」约束）。

---

## 1. 为什么选 vmxmy/xiaohongshu-mcp

小红书**没有官方发布 API**，只能走浏览器自动化（野路子）。可选开源实现：

| 项目 | 特点 | 草稿箱(save_draft) | 适合 |
|---|---|---|---|
| **vmxmy/xiaohongshu-mcp**（本方案选用） | xpzouying 的 fork，新增 `save_draft`/`publish_draft`/`list_drafts` | ✅ 有 | 需要「推草稿箱、人最后拍板」 |
| xpzouying/xiaohongshu-mcp（原版，9.1k★） | 最稳定，工具齐全，但只有 `publish_content` 直接发布 | ❌ 无 | 只需要直接发布、不需草稿 |

> 你明确要「推到草稿箱、最后看一眼」，所以选 **vmxmy fork**。若以后只想直接发，可换回 xpzouying。

---

## 2. 一键安装 + 登录（Windows）

直接双击运行仓库里的 **`setup_xiaohongshu_draft.bat`**，它会：

1. 在 `tools/xiaohongshu-mcp/` 下载 Windows 版二进制（自动用 `gh` 或 PowerShell 下载 `xiaohongshu-mcp-windows-amd64.zip`）。
2. 解压并找到可执行文件。
3. 后台启动 MCP 服务（端口 `18060`）。**首次启动会自动下载无头 Chromium（约 150MB）**，请保持联网。
4. 打印 MCP 客户端配置片段。

手动等价步骤：
```bash
# 下载（二选一）
gh release download -R vmxmy/xiaohongshu-mcp -p "xiaohongshu-mcp-windows-amd64.zip"
# 或
curl -L -o xiaohongshu-mcp-windows-amd64.zip https://github.com/vmxmy/xiaohongshu-mcp/releases/latest/download/xiaohongshu-mcp-windows-amd64.zip

# 解压后启动
xiaohongshu-mcp.exe --headless=true --port=18060
```

### 登录（必须，你本人做一次）
vmxmy 用 MCP 工具 `get_login_qrcode` 登录（没有单独的登录 exe）：
- **方式A（推荐）**：在 MCP 客户端（WorkBuddy / Cursor / Claude）里调用 `get_login_qrcode`，用**小红书 App 扫码**。
- **方式B**：用 MCP Inspector（`npx @modelcontextprotocol/inspector`）连 `http://localhost:18060/mcp`，调用 `get_login_qrcode` 扫码。

扫码后 Cookie 自动保存本机，**之后免登录**。

---

## 3. 接入 MCP 客户端

把下面这段加进你的 MCP 配置（如 `~/.workbuddy/mcp.json`、`.cursor/mcp.json`、`.vscode/mcp.json`），**重启客户端**生效：

```json
{
  "mcpServers": {
    "xiaohongshu": { "url": "http://localhost:18060/mcp" }
  }
}
```

验证服务起来了：
```bash
curl http://localhost:18060/mcp
```

---

## 4. 与本项目 run_loop 的衔接点

当前 `run_loop.py` 的 `generate` 阶段已留好「草稿箱接口」：**未部署 MCP 时优雅跳过**（不报错），部署后调用 `save_draft` 把文案+图片推到 App 草稿箱。

- 文件：`run_loop.py` 的 `generate` 阶段 → 调用 `xhs_mvp.py` 产出 `xhs_<选题>.json`（含 `_images_local` 本地图路径） → 通过 xiaohongshu-mcp 的 `save_draft`（传标题/正文/本地图绝对路径/话题标签）。
- 小红书内容规范（MCP 会校验，超限会报错）：
  - 标题 ≤ 20 字
  - 正文 ≤ 1000 字
  - 图片 ≤ 18 张
  - 同账号每日发布 ≤ 50 条（草稿箱不限，但正式发布注意频率）

> 下一步（待开发）：在 `run_loop.py` 里真正接入 `save_draft` 调用（读 `xhs_mvp` 产出的 json，映射字段）。当前为「接口已留、部署即通」状态。

---

## 5. 合规与风控提醒

- **实名 + 合规**：账号建议完成小红书实名；内容遵守平台规则，避免违规营销。
- **单一登录**：同一账号不要在多个网页端同时登录，否则 Cookie 失效需重新扫码。
- **频率控制**：发布/存草稿节奏放缓，避免被判定 spam。
- **Cookie 失效**：`get_login_qrcode` 重新扫码即可；旧 Cookie 文件删掉重来。
- **仅学习/自用运营**：该项目定位学习用途，禁止违规。

---

## 6. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 服务起不来 / 找不到浏览器 | 首次 Chromium 未下完或路径问题 | 保持联网重跑；或手动 `npx playwright install chromium` |
| `is_logged_in: false` | Cookie 过期 / 多端登录冲突 | 重新 `get_login_qrcode` 扫码 |
| 发布报 500 | 标题>20字 / 正文空 / Cookie 过期 | 检查字数、重新登录 |
| 图片上传失败 | 图不可公开访问或格式不对 | 用**本地绝对路径**图片（推荐），jpg/png ≤10MB |

---

## 7. 参考

- vmxmy fork：https://github.com/vmxmy/xiaohongshu-mcp
- 原版 xpzouying：https://github.com/xpzouying/xiaohongshu-mcp
- MCP Inspector：`npx @modelcontextprotocol/inspector`
