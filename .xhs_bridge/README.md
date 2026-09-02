# 本地桥接服务 local-xhs-bridge

## 它解决什么
`vmxmy/xiaohongshu-mcp` 的 Go 二进制写死 `playwright-go 1.49.1 driver`，该 driver 已从所有 CDN 下架（404），浏览器起不来。本服务用**标准 Node playwright**（driver 随 npm 包下发，避开 404）实现同款契约，让 `run_loop.py` 的 `generate --draft` / `draft` 阶段跑到一个真能开浏览器的活后端。

## 接口契约（与 run_loop.py 对齐）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/v1/health`     | 存活探针：返回 `status: healthy` |
| GET  | `/api/v1/ready`      | 就绪探针：playwright 模块 + 浏览器二进制是否就位（**不启动浏览器**，适合 k8s/Docker 健康检查） |
| GET  | `/api/v1/login/status` | 是否已有 cookie 文件 |
| GET  | `/api/v1/login/qrcode` | 触发扫码（headless 会被风控，不推荐；改用 `npm run login`） |
| POST | `/api/v1/draft`      | 真推草稿箱。请求体：`{ "title": "", "content": "", "tags": [], "images": ["本地图路径"] }` |

返回统一信封：`{ "success": bool, "code": string, "data": {}, "message": string }`。
无 cookie / cookie 失效 → `code: "NEED_LOGIN"`（run_loop.py 据此提示先登录）。

## 本地运行
```bash
cd .xhs_bridge
# 本项目已自带 .pw_test（playwright 本地包装，约 19M）；干净克隆后若缺失：
#   在此同级建 .pw_test 目录并 `npm install playwright`，bridge 会自动探测。
cp .env.example .env        # 按需改端口/路径
node bridge.js              # 监听 BRIDGE_PORT（默认 18070）
```
全链路验证：
```bash
python run_loop.py generate --inject pipeline/xhs_posts/xhs_<slug>.json --draft
```

## 一键扫码登录（推荐 ⭐）
**扫码这步必须真人 + 真实窗口**，headless（后台）浏览器会被小红书风控直接拦到报错页，截不出二维码。`/api/v1/login/qrcode` 那个接口就是 headless 的，不推荐用。本仓库自带独立脚本 `login.js`，强制真实窗口：
```bash
cd .xhs_bridge
npm run login          # 弹真实浏览器窗口；等价于 node login.js
```
流程：弹窗 → 手机「小红书 App」扫二维码 → 脚本每 2 秒自动检测登录态 → 成功即把 cookie 存到 `config.cookieFile`（默认 `xhs_cookies.json`，与 bridge 读的是同一份）。
- 之后 `python run_loop.py draft --json <笔记.json>` 直接进草稿箱，无需再登录。
- 旧 cookie 还在且有效 → 脚本直接复用，不弹扫码；已失效 → 提示重新扫码。
- ⚠️ 必须在**你本机有显示器**的环境跑（它会弹窗）。纯服务器 / 容器里跑正是会被风控的场景——那种环境请走下方「登录规模化」的真机 cookie 导入。

## Docker 部署（生产，彻底规避 driver 404）
```bash
docker build -t local-xhs-bridge .
docker run -d -p 18070:18070 \
  -v "$(pwd)/xhs_cookies.json:/app/xhs_cookies.json" \
  -e BRIDGE_HEADLESS=true \
  local-xhs-bridge
```
基础镜像 `mcr.microsoft.com/playwright` 已预装浏览器，Dockerfile 里 `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` 避免重复下载。

## ⚠️ 登录规模化（P0b，必读）
**不要在服务器上 headless 扫码**：数据中心 IP + headless 指纹会被小红书风控重定向到 `website-login/error`，QR 都截不出。正确姿势：
1. **真机 cookie 导入**：运营在真机/真浏览器登录后导出 `cookies.json` → 落盘到 `COOKIE_FILE`（或 `COOKIE_IMPORT_DIR` 目录，服务采用最新一份）→ 后端 `context.addCookies()` 复用。
2. **住宅代理** + **反检测指纹**（stealth 插件、固定 UA/时区/语言）。
3. **cookie 持久化 + 失效检测**：定期探 `creator.xiaohongshu.com`，跳登录页即失效，触发人工重新导出。
或走**官方开放平台 API**（企业号 App Key/Secret + 笔记发布权限，无浏览器、最稳，但有字数/图片数/频率限制）。

## 边界铁律
- **草稿箱 ≠ 正式发布**：机器只进草稿，人工在 App 里点「发布」最后拍板（合规）。
- 笔记至少 1 张图：注入 JSON 的 `images` 字段填**你手放的本地 PNG 路径**（本项目生图由人工用豆包完成，不接自动生图 provider；bridge + run_loop 只负责读真图 → 进草稿箱）。
