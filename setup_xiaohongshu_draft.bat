@echo off
chcp 65001 >nul
REM ============================================================
REM  极光AIGC · 小红书草稿箱(MCP) 安装 + 登录引导脚本
REM  用途：把成稿文案+图片自动推到「小红书 App 草稿箱」，你最后在 App 里拍板发布
REM  选用：vmxmy/xiaohongshu-mcp（fork of xpzouying，独有 save_draft 草稿箱能力）
REM  注意：仅本地运行，Cookie 留在你本机，数据不出本机（符合项目隐私要求）
REM ============================================================
setlocal
set "DIR=%~dp0tools\xiaohongshu-mcp"
if not exist "%DIR%" mkdir "%DIR%"
cd /d "%DIR%" || (echo 无法进入 %DIR% & pause & exit /b 1)

echo ============================================================
echo [1/3] 下载 xiaohongshu-mcp (Windows 版, 带 save_draft)
echo ============================================================
set "ZIP=xiaohongshu-mcp-windows-amd64.zip"
set "URL=https://github.com/vmxmy/xiaohongshu-mcp/releases/latest/download/%ZIP%"

if exist "%ZIP%" (
  echo 已存在 %ZIP%，跳过下载
) else (
  where gh >nul 2>nul && (
    echo 使用 gh 下载...
    gh release download -R vmxmy/xiaohongshu-mcp -p "%ZIP%" --clobber 2>nul
  )
  if not exist "%ZIP%" (
    echo 使用 PowerShell 下载...
    powershell -Command "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing"
  )
)
if not exist "%ZIP%" (
  echo [失败] 下载未成功。请手动到 https://github.com/vmxmy/xiaohongshu-mcp/releases 下载 %ZIP% 放到 %DIR%
  pause & exit /b 1
)

echo ============================================================
echo [2/3] 解压
echo ============================================================
if not exist xiaohongshu-mcp.exe (
  if not exist *xiaohongshu-mcp*.exe (
    powershell -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '.' -Force"
  )
)
REM 找到真正的 exe（zip 内文件名可能带后缀）
set "EXE="
for %%f in (xiaohongshu-mcp*.exe) do (set "EXE=%%f")
if not defined EXE (
  echo [失败] 解压后未找到 exe，请检查 %DIR%
  pause & exit /b 1
)
echo 找到可执行文件：%EXE%

echo ============================================================
echo [3/3] 启动 MCP 服务（后台, 端口 18060）
echo ============================================================
echo 首次启动会自动下载无头 Chromium（约150MB），请保持联网，稍等。
start "xiaohongshu-mcp" "%EXE%" --headless=true --port=18060
timeout /t 6 >nul
echo 服务已在后台启动。可验证： curl http://localhost:18060/mcp

echo.
echo ============================================================
echo  登录（必须，你本人操作一次即可，Cookie 本机保存）
echo ============================================================
echo  方式A（推荐）：在你常用的 MCP 客户端（WorkBuddy / Cursor / Claude）里调用工具
echo         get_login_qrcode
echo         然后用「小红书 App」扫屏幕上出现的二维码。
echo  方式B：浏览器打开 MCP Inspector（npx @modelcontextprotocol/inspector），
echo         连 http://localhost:18060/mcp，调用 get_login_qrcode 扫码。
echo  扫码成功后 Cookie 自动落盘，之后 save_draft / publish_content 都免登录。
echo.

echo ============================================================
echo  把下面这段加进你的 MCP 客户端配置（如 ~/.workbuddy/mcp.json
echo  或项目 .cursor/mcp.json / .vscode/mcp.json），重启客户端生效：
echo ------------------------------------------------------------
echo  {
echo    "mcpServers": {
echo      "xiaohongshu": { "url": "http://localhost:18060/mcp" }
echo    }
echo  }
echo ------------------------------------------------------------
echo.
echo  接好后，跑 run_loop.py 的 generate --draft 步骤即可把文案+图片
echo  推到你小红书 App 的「草稿箱」，你在 App 里最后看一眼再发布。
echo.
pause
