// 人工验证工具 manual_draft.js —— 专门解决"推草稿假成功"的最后一公里。
//
// 和 bridge.js 的差别：bridge 是 HTTP 服务，填完必须返回一个结果，被迫"报成功或关窗"；
// 本脚本是**一次性人工验证**：开一个你能看到、能点的【真窗口】，
// → 传图 → 打标题正文 →【绝不自动关窗】，停在那等你亲手点小红书那个保存按钮。
// 存完草稿箱计数一变，它立刻在终端打印 ✅。
//
// 用法（在你本机有显示器的终端跑）：
//   node manual_draft.js  <笔记.json>
//   node manual_draft.js  --help
const path = require("path");
const fs = require("fs");
const cfg = require("./config");

// ---------- 简易可用性：优先复用 bridge 的 playwright 解析 ----------
let chromium = null;
try { ({ chromium } = require(cfg.playwrightPath)); } catch (e) {
  console.error("playwright 加载失败: " + (e.message || e));
  process.exit(1);
}

// ---------- 参数 ----------
const args = process.argv.slice(2);
if (args.includes("--help") || args.includes("-h")) {
  console.log(`用法: node manual_draft.js <笔记.json>
它会在【真窗口】里打开小红书发布页，填入你 JSON 里的图/标题/正文/话题，
然后【停住不关】，等你在窗口里亲手点「暂存离开」(右下) 保存草稿。
看到终端打印 ✅ 才算真存进草稿箱。
JSON 里 images 请填本地图片路径；至少 1 张图。`);
  process.exit(0);
}
const jsonPath = args[0];
if (!jsonPath) { console.error("请传一个笔记 JSON 路径，例如 node manual_draft.js 笔记.json"); process.exit(1); }
if (!fs.existsSync(jsonPath)) { console.error("找不到 JSON: " + jsonPath); process.exit(1); }

// ---------- 读笔记 ----------
let payload;
try {
  payload = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
} catch (e) { console.error("JSON 解析失败: " + e.message); process.exit(1); }

// 归一化图片：支持 字符串 / {path}；转绝对路径；只留存在的本地文件
const ROOT = path.resolve(__dirname, "..");
function resolveImages(images) {
  const out = [];
  const skipped = [];
  for (const it of (images || [])) {
    let p = (typeof it === "string") ? it : (it && it.path);
    if (!p || /^https?:\/\//i.test(p)) { skipped.push(String(p) + "（非本地路径）"); continue; }
    if (!path.isAbsolute(p)) p = path.resolve(ROOT, p);
    if (fs.existsSync(p)) out.push(p); else skipped.push(p + "（文件不存在）");
  }
  return { out, skipped };
}
const { out: imgs, skipped } = resolveImages(payload.images || []);
for (const s of skipped) console.warn("⚠ 跳过图片: " + s);
if (!imgs.length) { console.error("至少需要 1 张存在的本地图片"); process.exit(1); }
const title = payload.title || payload.topic || "未命名笔记";
const content = payload.body || payload.hook || "";
const tags = payload.tags || [];
console.log("将填入:\n  图 " + imgs.length + " 张\n  标题: " + title + "\n  正文 " + content.length + " 字" + (tags.length ? "\n  话题: " + tags.join(" ") : ""));

// ---------- 启动真窗口 ----------
(async () => {
  // 强制真窗口：headless:false（用户必须在桌面看到并点击）；留大视口避免按钮被收。
  const browser = await chromium.launch({ headless: false, args: (cfg.browserArgs || ["--no-sandbox"]) });
  const ctx = await browser.newContext();
  // 注入 cook?  有 cookie 文件就复用，否则让用户登录
  if (fs.existsSync(cfg.cookieFile)) {
    try { const cookies = JSON.parse(fs.readFileSync(cfg.cookieFile, "utf-8")); if (cookies.length) await ctx.addCookies(cookies); } catch (_) {}
  }
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto(cfg.creatorUrl, { waitUntil: "domcontentloaded", timeout: 60000 });

  // 若被踢回登录页：提示手动扫码登录（真窗口下可正常显示二维码）
  if (page.url().includes("login")) {
    console.log("\n🔐 需要登录。请在【刚弹出的窗口】用小红书扫码登录，登录后本脚本会自动继续……");
    // 等登录成功：直到不再停在 login
    const dl = Date.now() + 120000;
    while (Date.now() < dl) {
      await page.waitForTimeout(2500);
      const u = page.url();
      const avatar = await page.$(".user-avatar, header .avatar, header .user").catch(() => null);
      if (!u.includes("login") || avatar) break;
    }
    if (page.url().includes("login")) {
      console.error("120 秒内未检测到登录成功，请重试。" );
      await browser.close().catch(()=>{}); process.exit(1);
    }
    // 存 cookie
    try { const c = await page.context().cookies(); if (c.length) fs.writeFileSync(cfg.cookieFile, JSON.stringify(c, null, 2)); } catch(_){}
    // 重新进发布页
    await page.goto(cfg.creatorUrl, { waitUntil: "domcontentloaded" }).catch(()=>{});
  }
  console.log("已进入发布页: " + page.url());

  // 初始草稿箱计数
  let before = null;
  try { before = await page.evaluate(() => { const m = document.body.innerText.match(/草稿箱[^\d]*(\d+)/); return m?parseInt(m[1],10):null; }); } catch(_){}

  // 传图
  try { await page.waitForSelector('input[type=file]', { state: 'attached', timeout: 30000 }); }
  catch (e) { console.error("30秒未出现图片上传框: " + e.message); await browser.close().catch(()=>{}); process.exit(1); }
  try { await page.locator('input[type=file]').first().setInputFiles(imgs); console.log("✅ 已上传 " + imgs.length + " 张图"); }
  catch (e) { console.error("传图失败: " + e.message); await browser.close().catch(()=>{}); process.exit(1); }

  // 等标题框
  const titleSel = 'input.d-text[placeholder="填写标题会有更多赞哦"], input.d-text';
  try { await page.waitForSelector(titleSel, { timeout: 40000 }); } catch (e) { console.error("编辑器未就绪: " + e.message); await browser.close().catch(()=>{}); process.exit(1); }
  // 打标题
  await page.click(titleSel).catch(()=>{});
  await page.keyboard.press("Control+A"); await page.keyboard.press("Delete");
  await page.keyboard.type(title, { delay: 12 });

  // 等图片处理
  await page.waitForTimeout(5000);

  // 打正文
  await page.click(".tiptap.ProseMirror").catch(()=>{});
  await page.keyboard.type(content, { delay: 8 });
  for (const t of tags) { const tag = t.startsWith("#") ? t : "#" + t; await page.keyboard.type(tag + " ", { delay: 15 }).catch(()=>{}); }
  // blur 收尾
  await page.evaluate(() => { const a = document.activeElement; if (a&&a.blur)a.blur(); }).catch(()=>{});
  await page.keyboard.press("Escape").catch(()=>{});
  await page.waitForTimeout(2000);
  console.log("✅ 标题/正文/话题已填入编辑器。 ");

  // ════ 关键：停住窗口，等你手动保存 ════
  console.log("\n══════════════════════════════════════════════════════════");
  console.log("  请在【你眼前那个窗口】里，用小红书自己的按钮保存：");
  console.log("    ① 检查标题/图/正文都填好了；");
  console.log("    ② 点右下角「暂存离开」（旧版叫「存草稿」）；");
  console.log("  ⚠️ 千万别点「发布/下一步」，那是直接对外发！");
  console.log("══════════════════════════════════════════════════════════");

  // 轮询草稿箱计数直到 +1，期间窗口绝不自动关。最长等你 15 分钟。
  const deadline = Date.now() + 15 * 60 * 1000;
  let lastAfter = null; let confirmed = false;
  while (Date.now() < deadline) {
    await page.waitForTimeout(3000);
    let after = null;
    try { after = await page.evaluate(() => { const m = document.body.innerText.match(/草稿箱[^\d]*(\d+)/); return m?parseInt(m[1],10):null; }).catch(()=>null); } catch(_){}
    if (after !== null) lastAfter = after;
    if (before !== null && after !== null && after > before) { confirmed = true; break; }
  }

  if (confirmed) {
    console.log("\n✅✅ 草稿箱计数从 " + before + " 变成 " + lastAfter + "，草稿【真】存进去了！");
    console.log("   请到手机 App 同账号草稿箱核对（同一账号应能看到）。");
  } else {
    // 你没在窗口里点保存 → 绝不假装成功，如实告知，并把窗口留着给你继续点。
    console.log("\n⚠️ 等了许久没看到草稿箱计数 +1（before=" + before + ", last=" + lastAfter + "）。");
    console.log("   窗口【没关】。请回到窗口点「暂存离开」，保存后看终端有没有出 ✅。");
    console.log("   若窗口已不在，说明你手动关了——那就到 App 草稿箱直接看有没有这篇。");
  }

  // 收尾：写一个结果文件供外部判断；然后停 10s 再关闭（给时间看提示）。
  const res = { success: confirmed, before, after: lastAfter, title, ts: new Date().toISOString() };
  try { fs.writeFileSync(path.join(__dirname, "manual_result.json"), JSON.stringify(res, null, 2)); } catch(_){}
  await page.waitForTimeout(8000);
  await browser.close().catch(() => {});
  process.exit(confirmed ? 0 : 3);
})().catch(e => { console.error("运行出错: " + (e.message||e)); try { process.exit(1); } catch(_){} });
