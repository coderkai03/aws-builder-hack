// Step 2: render demo/cinematic/launch.html to video at 1920x1080.
// Usage: node demo/cinematic/render.js <out-dir>   (prints the trim offset in seconds)
const { chromium } = require("playwright");
const path = require("path");

const OUT = process.argv[2] || "demo/cinematic/out";
(async () => {
  const browser = await chromium.launch({ args: ["--disable-gpu-vsync"] });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 },
                                         recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } } });
  const t0 = Date.now();
  const page = await ctx.newPage();
  await page.goto("file://" + path.resolve(__dirname, "launch.html"));
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map((i) => i.complete || new Promise((r) => (i.onload = r))));
  });
  // preload every shot so nothing pops in late
  await page.evaluate(() => Promise.all(["full", "funnel", "diagnosis", "experiment_pending", "approve_button",
    "experiment_killed", "kill_event", "experiment_done", "memo"].map((n) => new Promise((r) => {
      const i = new Image(); i.onload = r; i.onerror = r; i.src = `assets/${n}.png`; }))));
  await page.waitForTimeout(500);
  const offset = (Date.now() - t0) / 1000;
  await page.evaluate(() => window.start());
  const total = await page.evaluate(() => window.TOTAL);
  await page.waitForTimeout(total * 1000 + 500);
  await ctx.close(); await browser.close();
  console.log(JSON.stringify({ offset, total }));
})().catch((e) => { console.error(e); process.exit(1); });
