@echo off
chcp 65001 >nul
title 小红书爆款深挖 · 一键安装
echo ============================================================
echo  小红书竞品爆款深挖系统 - 一键安装
echo  (自动装 Python 依赖 + 下载 MediaCrawler 爬虫)
echo ============================================================
echo.

rem ---------- 0. 检查 Python ----------
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+：
    echo   https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    pause
    exit /b 1
)
python --version
echo.

rem ---------- 1. 建虚拟环境 ----------
if not exist .venv (
    echo [1/4] 创建虚拟环境 .venv ...
    python -m venv .venv
) else (
    echo [1/4] .venv 已存在，跳过
)
call .venv\Scripts\activate.bat
echo.

rem ---------- 2. 装 Python 依赖 ----------
echo [2/4] 安装 Python 依赖（pillow/numpy/rapidocr/requests/openpyxl）...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [警告] 依赖安装可能未完全成功，请查看上方报错
)
echo.

rem ---------- 3. 下载 MediaCrawler ----------
if not exist tools\MediaCrawler\main.py (
    echo [3/4] 下载 MediaCrawler 爬虫（约 1-2 分钟）...
    if not exist tools mkdir tools
    git clone --depth 1 https://github.com/NanmiCoder/MediaCrawler.git tools\MediaCrawler
    if %errorlevel% neq 0 (
        echo [错误] MediaCrawler 下载失败，请确认已安装 Git：
        echo   https://git-scm.com/download/win
        pause
        exit /b 1
    )
    echo      安装 MediaCrawler 依赖 + 浏览器内核...
    python -m pip install -r tools\MediaCrawler\requirements.txt -q
    python -m playwright install chromium
) else (
    echo [3/4] MediaCrawler 已存在，跳过
)
echo.

rem ---------- 4. 生成 .env ----------
if not exist .env (
    echo [4/4] 生成 .env 配置模板（请用编辑器填写你的 API Key）...
    copy .env.example .env >nul
    echo.
    echo   请打开 .env 填写：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
    echo   （任选一家大模型：DeepSeek / Kimi / 通义 / GLM / 豆包 / Ollama）
) else (
    echo [4/4] .env 已存在，跳过
)
echo.

echo ============================================================
echo  安装完成！
echo.
echo  下一步：
echo   1. 编辑 .env，填入你的大模型 API
echo   2. 编辑 pipeline\competitor_targets.json 填你的关键词
echo   3. 运行：python pipeline\run_baokuan_digest.py --with-llm
echo      （首次会弹浏览器，用你的小红书账号扫码登录）
echo ============================================================
pause
