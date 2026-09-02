// login.js —— 一键扫码登录：弹真实浏览器窗口，你用小红书 App 扫码，脚本自动存 cookie。
//
// 为什么单独写这个脚本（而不是复用 bridge 的 /api/v1/login/qrcode）？
//   沙箱里 bridge 跑在「无头（后台）浏览器」，小红书风控会直接把扫码拦到报错页。
//   本脚本强制 headless:false，弹你本机真实窗口，真人扫码能过风控，最稳。
//
// 用法：
//   npm run login          # 弹窗 → 手机扫码 → 自动存 cookie
//   或 node login.js
//
// 登录成功后把 cookie 存到 config.cookieFile（与 bridge 读取的是同一个文件），
// 之后 `python run_loop.py draft --json <笔记.json>` 就能自动进草稿箱，无需再登录。
const fs = require("fs");
const cfg = require("./config");
const { chromium } = require(cfg.playwrightPath);

const LOGIN_URL = "https://www.xiaohongshu.com/login";
const POLL_MS = 2000;          // 每 2 秒检测一次登录态
const TIMEOUT_MS = 120000;     // 给用户 2 分钟扫码

function detectLoggedIn(page) {
  return Promise.all([
    page.url(),
    page.$(".user-avatar, .avatar, header .user, .side-bar-avatar, .user-info").catch(() => null),
    page.evaluate(() => document.body.innerText.slice(0, 400)).catch(() => ""),
  ]).then(([u, avatar, txt]) => {
    return !u.includes("login") || !!avatar ||
      txt.includes("登录成功") || txt.includes("我的主页") || txt.includes("创作中心");
  });
}

(async () => {
  console.log("🌐 正在打开小红书登录页（真实浏览器窗口，请准备扫码）...");
  const browser = await chromium.launch({ headless: false, args: cfg.browserArgs });
  const ctx = await browser.newContext();

  // 已有 cookie：先试着直接复用，省得再扫一次
  let reusedSession = false;
  if (fs.existsSync(cfg.cookieFile)) {
    try {
      const old = JSON.parse(fs.readFileSync(cfg.cookieFile, "utf-8"));
      if (old.length) {
        await ctx.addCookies(old);
        const p = await ctx.newPage();
        await p.goto(cfg.creatorUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
        await p.waitForTimeout(1500);
        const url = p.url();
        if (!url.includes("login")) {
          console.log("✅ 检测到已有有效登录态，无需重新扫码。");
          await browser.close();
          process.exit(0);
        }
        reusedSession = true;
        console.log("⚠️ 旧 cookie 已失效，请在弹窗里重新扫码。");
      }
    } catch (_) { /* 损坏的 cookie 文件，忽略，走重新登录 */ }
  }

  const page = reusedSession ? ctx.pages()[0] : await ctx.newPage();
  await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" }).catch(() => {});
  console.log("📱 请用手机「小红书 App」扫描弹窗中的二维码登录。");
  console.log("   登录成功后本脚本会自动检测并保存登录态，不需要点任何其它按钮。");

  const deadline = Date.now() + TIMEOUT_MS;
  let loggedIn = false;
  while (Date.now() < deadline) {
    await page.waitForTimeout(POLL_MS);
    if (await detectLoggedIn(page)) { loggedIn = true; break; }
  }

  if (!loggedIn) {
    console.log("⏰ 2 分钟内未检测到登录，cookie 未保存。请重新运行 `npm run login`。");
    await browser.close();
    process.exit(1);
  }

  // 登录成功：补抓 creator 域 cookie，确保草稿箱能直接用
  await page.goto(cfg.creatorUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForTimeout(2000);
  const cookies = await ctx.cookies();
  fs.writeFileSync(cfg.cookieFile, JSON.stringify(cookies, null, 2));
  console.log("✅ 登录成功！已将 cookie 保存到:", cfg.cookieFile);
  console.log("   接下来运行:  python run_loop.py draft --json <你的笔记.json>   即可自动进草稿箱。");
  await browser.close();
  process.exit(0);
})().catch((e) => {
  console.error("❌ 登录脚本异常:", e);
  process.exit(1);
});
