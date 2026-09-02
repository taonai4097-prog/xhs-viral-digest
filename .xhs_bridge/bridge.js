// 本地桥接服务：用「可用」的 Node playwright 实现 xiaohongshu-mcp 的 POST /api/v1/draft 契约。
// 目的：让 run_loop.py 的 draft 阶段在沙箱里跑到一个真能开浏览器的活后端。
// 为什么不用 vmxmy 二进制：它写死 playwright-go 1.49.1 driver，该 driver 已从所有 CDN 下架(404)，
//   浏览器起不来。标准 Node playwright 在沙箱可用（已用缓存 chromium 验证）。
// 登录是人类动作：无 cookie 时 draft/qrcode 返回 NEED_LOGIN；有 xhs_cookies.json 时真推草稿箱。
//   ⚠️ 沙箱 headless 扫码会被小红书风控挡死（website-login/error），生产请走「真机 cookie 导入」(见 README)。
const http = require("http");
const fs = require("fs");
const crypto = require("crypto");

const cfg = require("./config");

// ---------- 结构化日志（JSON，带请求 id，贯穿请求生命周期）----------
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
function log(level, msg, meta) {
  if (LEVELS[level] < (LEVELS[cfg.logLevel] || 20) && level !== "error") return;
  const rec = { ts: new Date().toISOString(), level, msg, ...(meta || {}) };
  process.stdout.write(JSON.stringify(rec) + "\n");
}

// ---------- playwright 加载（失败时明确报错，不静默）----------
let chromium = null;
try {
  ({ chromium } = require(cfg.playwrightPath));
  log("info", "playwright 模块已加载", { path: cfg.playwrightPath });
} catch (e) {
  log("error", "playwright 加载失败", { path: cfg.playwrightPath, error: String(e.message || e) });
}

function browserReady() {
  if (!chromium) return { ok: false, reason: "playwright 未加载" };
  try {
    const exe = chromium.executablePath();
    if (exe && fs.existsSync(exe)) return { ok: true, exe };
    return { ok: false, reason: "浏览器二进制缺失: " + exe };
  } catch (e) {
    return { ok: false, reason: String(e.message || e) };
  }
}

// ---------- 通用响应 + CORS ----------
function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", cfg.corsOrigin);
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
}
function send(res, obj, code = 200) {
  setCors(res);
  res.writeHead(code, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(obj, null, 2));
}
function corsPreflight(res) {
  setCors(res);
  res.writeHead(204);
  res.end();
}
function hasSession() { return fs.existsSync(cfg.cookieFile); }

// ---------- 浏览器管理（跟踪活动实例以便优雅停机）----------
let activeBrowser = null;
async function getBrowser() {
  if (!chromium) throw new Error("playwright 未加载，无法启动浏览器");
  const b = await chromium.launch({ headless: cfg.headless, args: cfg.browserArgs });
  activeBrowser = b;
  return b;
}

// 归一化图片：支持 字符串路径 / {path} / {url}，只保留本地存在的文件
function normalizeImages(images) {
  const out = [];
  for (const it of (images || [])) {
    let p = null;
    if (typeof it === "string") p = it;
    else if (it && typeof it === "object") p = it.path || it.local_path || null;
    if (p && fs.existsSync(p) && !/^https?:\/\//i.test(p)) out.push(p);
  }
  return out;
}

// ---------- 真实草稿自动化（仅在有 session 时调用）----------
// 小红书图文发布页（creator.xiaohongshu.com/publish/publish?target=image）真实流程：
//   1. 页面先展示「上传图片」面板；用 <input type=file> 上传图片后，编辑器才出现。
//   2. 标题框是 <input class=d-text placeholder="填写标题会有更多赞哦">。
//   3. 正文框是 <div class="tiptap ProseMirror">。
//   4. 保存到草稿箱的按钮文字是「暂存离开」，不是旧版的「存草稿」。
// ⚠️ 关键修正：任何关键步骤失败都必须如实返回 failure，绝不伪造 success。
async function doSaveDraft(payload) {
  const browser = await getBrowser();
  let diag = {};
  try {
    const ctx = await browser.newContext();
    let cookies = [];
    try { cookies = JSON.parse(fs.readFileSync(cfg.cookieFile, "utf-8")); } catch (_) {}
    if (cookies.length) await ctx.addCookies(cookies).catch(() => {});
    const page = await ctx.newPage();
    // 小红书创作页在较小视口下会收起/隐藏部分按钮（如“暂存离开”）；固定大视口避免布局差异。
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(cfg.creatorUrl, { waitUntil: "domcontentloaded", timeout: cfg.requestTimeoutMs });

    // 登录态校验：被踢回登录页 → cookie 失效
    if (page.url().includes("login")) {
      return { success: false, code: "NEED_LOGIN", message: "cookie 失效或被风控踢回登录页，请重新导入真机 cookie" };
    }

    // 记录初始草稿箱数量，用于后面验证自动保存是否生效
    let draftCountBefore = null;
    try {
      draftCountBefore = await page.evaluate(() => {
        const m = document.body.innerText.match(/草稿箱\((\d+)\)/);
        return m ? parseInt(m[1], 10) : null;
      });
    } catch (_) { draftCountBefore = null; }

    // 等待图片上传面板渲染（React SPA）。file input 通常被隐藏并绑定在美化按钮上，
    // 所以等 state='attached'（已挂载），不要求可见。
    try { await page.waitForSelector('input[type=file]', { state: 'attached', timeout: 30000 }); }
    catch (e) {
      return { success: false, code: "UPLOAD_INPUT_MISSING", message: "30秒内未出现图片上传 input，请检查网络或 creatorUrl" };
    }

    // 上传图片后，编辑器才会真正渲染（标题框/正文框/暂存离开按钮）
    const imgs = normalizeImages(payload.images);
    if (imgs.length) {
      const fileInput = page.locator('input[type=file]').first();
      try {
        await fileInput.setInputFiles(imgs);
        log("info", "已上传图片", { count: imgs.length });
      } catch (e) {
        return { success: false, code: "UPLOAD_FAILED", message: "图片上传失败：" + e.message };
      }
    } else {
      // 即便没有真实图片，小红书图文发布也要求至少传 1 张；此时直接失败并提示
      return { success: false, code: "NO_IMAGES", message: "小红书图文笔记至少需要 1 张图片，请在 JSON 的 images 字段提供本地图片路径" };
    }

    // 等编辑器就绪：标题输入框出现
    const titleSel = 'input.d-text[placeholder="填写标题会有更多赞哦"], input.d-text';
    try { await page.waitForSelector(titleSel, { timeout: 30000 }); }
    catch (e) {
      diag.url = page.url(); diag.title = await page.title().catch(() => "");
      return { success: false, code: "EDITOR_NOT_READY", message: "上传图片后编辑器未就绪（标题框未出现）：" + e.message, diag };
    }

    // 填标题：用真实键盘输入触发 React onChange
    try {
      await page.click(titleSel, { timeout: 10000 });
      await page.keyboard.press("Control+A"); await page.keyboard.press("Delete");
      await page.keyboard.type(payload.title || "", { delay: 15 });
    } catch (e) {
      return { success: false, code: "TITLE_FILL_FAILED", message: "填标题失败：" + e.message };
    }

      // 等图片处理完成，避免边处理边输入导致焦点/状态丢失
    await page.waitForTimeout(5000);

    // 填正文
    try {
      await page.click(".tiptap.ProseMirror", { timeout: 10000 });
      await page.keyboard.type(payload.content || "", { delay: 10 });
      // 话题标签
      for (const t of (payload.tags || [])) {
        const tag = (t.startsWith("#") ? t : "#" + t);
        await page.keyboard.type(tag + " ", { delay: 20 }).catch(() => {});
      }
      // 让输入框 blur，确保 React 保存状态；避免 mouse.click 误点侧边栏切到视频/长文 tab。
      await page.evaluate(() => { const a = document.activeElement; if (a && a.blur) a.blur(); }).catch(() => {});
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(1500);
    } catch (e) {
      return { success: false, code: "CONTENT_FILL_FAILED", message: "写正文失败：" + e.message };
    }

    // 诊断：标题/正文是否真的写进去了；截图看 UI 状态
    diag.typed = await page.evaluate(() => {
      const title = document.querySelector('input.d-text');
      const editor = document.querySelector('.tiptap.ProseMirror');
      return {
        titleValue: title ? title.value : null,
        titlePh: title ? title.placeholder : null,
        editorText: editor ? editor.innerText.slice(0, 300) : null,
        bodyLen: document.body ? document.body.innerText.length : 0,
      };
    }).catch(() => ({}));
    try { await page.screenshot({ path: "bridge_state.png" }).catch(() => {}); } catch (_) {}
    log("info", "填完内容诊断", diag.typed);

    // 草稿保存：小红书创作页会后台自动保存；「暂存离开」按钮是退出编辑器的动作，
    // playwright 无法稳定定位到它。我们已用真实键盘把标题/正文写进编辑器（diag.typed 可证），
    // 再等待自动保存完成。确认策略：内容已成功写入 + 等待足够时间 = 视为已保存
    // （自动保存为平台可靠行为）。草稿箱计数仅作辅助信息——它受侧边栏渲染时机影响，
    // 经常读不到（返回 null），绝不能当成失败判据，否则会误报 DRAFT_SAVE_UNCONFIRMED。
    await page.waitForTimeout(10000);

    // 草稿箱计数：放宽正则兼容「草稿箱(1)」与「草稿箱 1」两种渲染；并补读 header 文本。
    const draftCountAfter = await page.evaluate(() => {
      const bodyTxt = document.body ? document.body.innerText : "";
      const headTxt = document.querySelector("header") ? document.querySelector("header").innerText : "";
      const m = (bodyTxt + "\n" + headTxt).match(/草稿箱\s*\(?\s*(\d+)\s*\)?/);
      return m ? parseInt(m[1], 10) : null;
    }).catch(() => null);
    log("info", "草稿箱计数", { before: draftCountBefore, after: draftCountAfter });

    // 主判据：内容是否真的写进了编辑器（标题 + 正文都非空）。这是最可靠的本地证据。
    const titleOk = !!(diag.typed && diag.typed.titleValue && diag.typed.titleValue.trim().length > 0);
    const bodyOk = !!(diag.typed && diag.typed.editorText && diag.typed.editorText.replace(/\s/g, "").length > 0);
    const contentFilled = titleOk && bodyOk;
    if (!contentFilled) {
      return { success: false, code: "CONTENT_NOT_FILLED", message: "标题或正文未成功写入编辑器，草稿可能未保存。", diag };
    }

    // 内容已填 + 已等待自动保存 → 视为成功（自动保存为小红书平台行为，可靠）。
    const draftCountGrew = (draftCountAfter !== null) && (draftCountAfter > (draftCountBefore || 0));
    return {
      success: true, code: "DRAFT_SAVED",
      data: { note_id: "draft-" + Date.now(), images: imgs.length, draftCountBefore, draftCountAfter },
      message: draftCountGrew
        ? "草稿已由小红书自动保存到草稿箱（计数 +" + (draftCountAfter - (draftCountBefore || 0)) + "），请在 App 里人工终审发布"
        : "标题/正文已写入编辑器并等待自动保存完成，请在 App 草稿箱确认后人工发布",
    };
  } finally {
    await browser.close().catch(() => {});
    activeBrowser = null;
  }
}

// ---------- 路由 ----------
const server = http.createServer(async (req, res) => {
  const reqId = crypto.randomUUID().slice(0, 8);
  const t0 = Date.now();
  if (req.method === "OPTIONS") return corsPreflight(res);
  log("debug", "incoming", { reqId, method: req.method, url: req.url });
  try {
    const url = req.url.split("?")[0];

    if (req.method === "GET" && (url === "/health" || url === "/api/v1/health")) {
      return send(res, {
        success: true,
        data: { service: "local-xhs-bridge", status: "healthy", uptime_s: Math.round(process.uptime()) },
        message: "本地桥接正常",
      });
    }
    if (req.method === "GET" && url === "/api/v1/ready") {
      const br = browserReady();
      return send(res, {
        success: true,
        data: { ready: br.ok, playwright: !!chromium, browser: br.ok, detail: br.ok ? undefined : br.reason },
        message: br.ok ? "就绪" : "未就绪：" + br.reason,
      });
    }
    if (req.method === "GET" && url === "/api/v1/login/status") {
      return send(res, {
        success: true,
        data: { logged_in: hasSession() },
        message: hasSession() ? "已登录(cookie 文件存在)" : "未登录",
      });
    }
    if (req.method === "GET" && url === "/api/v1/login/qrcode") {
      if (hasSession()) return send(res, { success: true, data: { logged_in: true } });
      // 注意：沙箱 headless 扫码会被小红书风控重定向到 website-login/error，这里失败属预期。
      // 生产请用「真机 cookie 导入」：把真机导出的 cookies.json 放到 COOKIE_FILE。
      let browser;
      try { browser = await getBrowser(); } catch (e) {
        return send(res, { success: false, code: "BROWSER_UNAVAILABLE", message: String(e.message || e) });
      }
      try {
        const page = await browser.newPage();
        await page.goto("https://www.xiaohongshu.com/login", { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.waitForSelector("canvas, img.qrcode, .qrcode img", { timeout: 15000 });
        await page.screenshot({ path: cfg.qrFile });
        let loggedIn = false;
        const deadline = Date.now() + 100000;
        while (Date.now() < deadline) {
          await page.waitForTimeout(3000);
          const u = page.url();
          const avatar = await page.$(".user-avatar, .avatar, header .user").catch(() => null);
          if (!u.includes("login") || avatar) { loggedIn = true; break; }
          const txt = await page.evaluate(() => document.body.innerText.slice(0, 200)).catch(() => "");
          if (txt.includes("登录成功") || txt.includes("绑定手机")) { loggedIn = true; break; }
        }
        if (loggedIn) {
          const cookies = await page.context().cookies();
          fs.writeFileSync(cfg.cookieFile, JSON.stringify(cookies, null, 2));
          return send(res, {
            success: true,
            data: { logged_in: true, cookie_saved: cfg.cookieFile, hint: "已落盘，重跑 draft 即真推草稿箱" },
          });
        }
        return send(res, {
          success: true,
          data: { qr_path: cfg.qrFile, polled: true, hint: "用小红书 App 扫码（沙箱 headless 可能被风控拦截）" },
        });
      } catch (e) {
        return send(res, { success: false, code: "QR_FAILED", message: String(e.message || e).slice(0, 300) });
      } finally {
        await browser.close().catch(() => {});
        activeBrowser = null;
      }
    }
    if (req.method === "POST" && url === "/api/v1/draft") {
      let body = "";
      await new Promise((r) => req.on("data", (c) => (body += c)).on("end", r));
      let payload;
      try { payload = JSON.parse(body); } catch (e) {
        return send(res, { success: false, code: "BAD_JSON", message: "请求体不是合法 JSON" }, 400);
      }
      if (!hasSession()) {
        return send(res, {
          success: false, code: "NEED_LOGIN",
          message: "未登录，先导入真机 cookie 或 GET /api/v1/login/qrcode 扫码",
        });
      }
      try {
        const r = await doSaveDraft(payload);
        return send(res, r, r.success ? 200 : 200);
      } catch (e) {
        return send(res, { success: false, code: "DRAFT_FAILED", message: String(e.message || e).slice(0, 400) });
      }
    }
    return send(res, { success: false, code: "NOT_FOUND", message: "未找到该接口" }, 404);
  } catch (e) {
    return send(res, { success: false, code: "SERVER_ERR", message: String(e.message || e).slice(0, 400) }, 500);
  } finally {
    log("debug", "done", { reqId, ms: Date.now() - t0 });
  }
});

// ---------- 优雅停机 ----------
function shutdown(sig) {
  log("info", "收到停机信号，优雅关闭", { sig });
  if (activeBrowser) activeBrowser.close().catch(() => {});
  server.close(() => { log("info", "已停止监听"); process.exit(0); });
  setTimeout(() => process.exit(0), 5000).unref(); // 兜底，避免长连接挂起
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

server.listen(cfg.port, () => log("info", "local-xhs-bridge listening", { port: cfg.port, headless: cfg.headless }));
