// bridge 配置：全部来自环境变量，启动时集中加载、缺省值兜底、快速失败友好。
// 仅 .env.example 入库，真实 .env 不提交（已在仓库 .gitignore）。
const path = require("path");
const fs = require("fs");

// dotenv 为可选依赖：沙箱实测靠 .pw_test 里的 playwright，不强求 dotenv。
let dotenv = null;
try { dotenv = require("dotenv"); } catch (_) { dotenv = null; }
if (dotenv) {
  try { dotenv.config({ path: path.join(__dirname, ".env") }); } catch (_) {}
}

// playwright 解析顺序：显式 PLAYWRIGHT_PATH → 本地 .pw_test 安装 → 全局默认
function resolvePlaywright() {
  if (process.env.PLAYWRIGHT_PATH) return process.env.PLAYWRIGHT_PATH;
  const local = path.join(__dirname, "..", ".pw_test", "node_modules", "playwright");
  if (fs.existsSync(local)) return local;
  return "playwright";
}

const cfg = {
  port: parseInt(process.env.BRIDGE_PORT || "18070", 10),
  playwrightPath: resolvePlaywright(),
  cookieFile: path.resolve(__dirname, process.env.COOKIE_FILE || "xhs_cookies.json"),
  qrFile: path.resolve(__dirname, process.env.QR_FILE || "xhs_qr.png"),
  creatorUrl: process.env.CREATOR_URL ||
    "https://creator.xiaohongshu.com/publish/publish?source=official&target=image",
  headless: (process.env.BRIDGE_HEADLESS || "true").toLowerCase() !== "false",
  browserArgs: (process.env.BROWSER_ARGS || "--no-sandbox").split(/\s+/).filter(Boolean),
  requestTimeoutMs: parseInt(process.env.REQUEST_TIMEOUT_MS || "60000", 10),
  // 生产请将 CORS_ORIGIN 改为具体前端域名；本地联调默认放开。
  corsOrigin: process.env.CORS_ORIGIN || "*",
  logLevel: process.env.BRIDGE_LOG_LEVEL || "info",
  // 真机 cookie 导入目录（P0b 规模化）：把真机导出的 cookies.json 丢这里，服务采用最新一份。
  cookieImportDir: process.env.COOKIE_IMPORT_DIR
    ? path.resolve(process.env.COOKIE_IMPORT_DIR)
    : path.dirname(path.resolve(__dirname, process.env.COOKIE_FILE || "xhs_cookies.json")),
};

module.exports = cfg;
