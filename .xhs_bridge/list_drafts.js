// list_drafts.js —— 只读：用当前 cookie 打开小红书创作中心的「草稿」列表页，
// 把草稿标题抓出来，验证刚才手动点「暂存」的稿子是否真在这个会话的草稿箱里。
// 用法: node list_drafts.js
const fs = require("fs");
const cfg = require("./config");
let chromium = null;
try { ({ chromium } = require(cfg.playwrightPath)); } catch (e) { console.error("pw 加载失败: "+(e.message||e)); process.exit(1); }

(async () => {
  const browser = await chromium.launch({ headless: true, args: cfg.browserArgs });
  const ctx = await browser.newContext();
  try { const c = JSON.parse(fs.readFileSync(cfg.cookieFile, "utf-8")); if (c.length) await ctx.addCookies(c); } catch (_) {}
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  // 创作中心草稿列表候选地址（先试最正统的）
  const urls = [
    "https://creator.xiaohongshu.com/publish/publish?source=official",
    "https://creator.xiaohongshu.com/new/note-manager?type=draft",
    "https://creator.xiaohongshu.com/note-manager/draft",
    "https://creator.xiaohongshu.com/draft",
  ];
  let found = [];
  for (const u of urls) {
    try {
      await page.goto(u, { waitUntil: "domcontentloaded", timeout: 30000 });
      await page.waitForTimeout(4000);
      const urlNow = page.url();
      // 抓正文里草稿条目/标题文本
      const txt = await page.evaluate(() => document.body ? document.body.innerText : "").catch(()=>"");
      found.push({ url: u, finalUrl: urlNow.slice(0,90), sample: txt.replace(/\n+/g," | ").slice(0, 500) });
    } catch (e) { found.push({ url: u, error: String(e.message||e).slice(0,100) }); }
  }
  console.log(JSON.stringify(found, null, 2));
  await browser.close().catch(()=>{});
})().catch(e => { console.error("ERR: "+(e.message||e)); try{process.exit(1);}catch(_){} });
