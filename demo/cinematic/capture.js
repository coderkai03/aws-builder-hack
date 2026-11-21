// Step 1 of the cinematic cut: drive a LIVE run and capture crisp element screenshots + real numbers.
// Usage (server running on :8000): node demo/cinematic/capture.js <out-dir>
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = "http://localhost:8000";
const OUT = process.argv[2] || "demo/cinematic/assets";
fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1600, height: 900 }, deviceScaleFactor: 2,
    recordVideo: { dir: OUT + "/raw", size: { width: 1600, height: 900 } },
  });
  const page = await ctx.newPage();
  const shot = async (sel, name) => {
    const el = page.locator(sel).first();
    await el.scrollIntoViewIfNeeded();
    await el.screenshot({ path: `${OUT}/${name}.png` });
    console.log("shot", name);
  };
  const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

  await page.request.post(`${BASE}/api/reset`);
  await page.goto(`${BASE}/`);
  await sleep(1500);
  await page.screenshot({ path: `${OUT}/header.png`, clip: { x: 0, y: 0, width: 1600, height: 64 } });

  await page.click("text=Seed baseline"); await sleep(3500); log("seeded");
  await shot("main .stack >> nth=0 >> .panel >> nth=0", "funnel");

  await page.click("text=Run agent");
  await page.waitForSelector("text=Approve launch", { timeout: 180000 }); await sleep(1500); log("designed");
  await shot("#expPanel", "experiment_pending");
  await shot(".audit .ev.diagnose >> nth=0", "diagnosis");
  await shot("text=Approve launch", "approve_button");

  await page.click("text=Approve launch"); await sleep(2000);
  await page.click("#simBtn"); log("traffic");
  await page.waitForSelector(".badge.killed", { timeout: 180000 }); await sleep(1500); log("killed");
  await shot("#expPanel", "experiment_killed");
  await shot(".audit .ev.guardrail_kill", "kill_event");
  await shot("main .stack >> nth=1 >> .panel >> nth=1", "chart_mid");

  await page.waitForSelector("text=Decision memo", { timeout: 300000 }); await sleep(2500); log("decided");
  await page.click("#simBtn"); // stop traffic so the end state is stable
  await shot("#expPanel", "experiment_done");
  await shot("main .stack >> nth=1 >> .panel >> nth=1", "chart_done");
  await shot("#memoPanel", "memo");
  await page.screenshot({ path: `${OUT}/full.png` });

  const state = await (await page.request.get(`${BASE}/api/state`)).json();
  const evidence = await (await page.request.get(`${BASE}/api/evidence`)).json();
  fs.writeFileSync(`${OUT}/run.json`, JSON.stringify({ state, evidence }, null, 1));
  await ctx.close(); await browser.close();
  log("done");
})().catch((e) => { console.error(e); process.exit(1); });
