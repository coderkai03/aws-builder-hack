// Records the North Star demo video against a running server (uvicorn northstar.server:app --port 8000).
// Usage: node demo/record.js <output-dir>
const { chromium } = require("playwright");

const BASE = "http://localhost:8000";
const OUT = process.argv[2] || "demo/raw";
const W = 1536, H = 864;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function caption(page, text, ms = 0) {
  await page.evaluate((t) => {
    let el = document.getElementById("ns-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "ns-caption";
      el.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);max-width:1100px;z-index:9999;" +
        "background:rgba(10,14,24,.94);color:#fff;border:1px solid #7c9cff;border-radius:12px;padding:12px 20px;" +
        "font:600 19px/1.4 Inter,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.5);text-align:center;transition:opacity .25s";
      document.body.appendChild(el);
    }
    el.style.opacity = t ? "1" : "0";
    if (t) el.innerHTML = t;
  }, text);
  if (ms) await sleep(ms);
}

async function highlight(page, selector, on = true) {
  await page.evaluate(([s, on]) => {
    const el = document.querySelector(s);
    if (el) { el.style.transition = "box-shadow .3s"; el.style.boxShadow = on ? "0 0 0 3px #f5b942" : ""; }
  }, [selector, on]);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT, size: { width: W, height: H } } });
  const page = await ctx.newPage();
  const t0 = Date.now();
  const log = (m) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${m}`);

  // Clean slate before anything is on screen.
  await page.request.post(`${BASE}/api/reset`);

  await page.goto(`${BASE}/video/slides.html?s=title`); log("title");
  await sleep(7000);
  await page.goto(`${BASE}/video/slides.html?s=problem`); log("problem");
  await sleep(12000);

  await page.goto(`${BASE}/`); await sleep(1200); log("dashboard");
  await caption(page, "North Star's control room. Every integration pill on top is <b>live</b>: Superlinked, Statsig, Amplitude, SingleStore, Cognee.", 5500);

  await page.click("text=Seed baseline"); log("seed");
  await caption(page, "We seed 3,000 simulated visitors into <b>Acme Cloud</b>'s signup funnel. Events land in SingleStore and stream to Amplitude.", 5000);
  await highlight(page, "#steps");
  await caption(page, "The weakest step jumps out: only ~35% of people who start signing up finish.", 4000);
  await highlight(page, "#steps", false);

  await page.click("text=Run agent"); log("plan");
  await caption(page, "<b>Run agent.</b> North Star reads the funnel, split by mobile vs desktop...", 6000);
  await caption(page, "...recalls lessons from past experiments in its <b>Cognee</b> knowledge graph...", 7000);
  await caption(page, "...and reasons over the data with <b>Qwen3.8 27B on Superlinked SIE</b>, using strict JSON-schema output.", 0);
  await page.waitForSelector("text=Approve launch", { timeout: 150000 }); log("designed");
  await sleep(1200);
  await caption(page, "It designed an experiment: variants are just parameters, so nothing needs a deploy. Its hypothesis cites real numbers.", 7000);
  await highlight(page, "#expPanel");
  await caption(page, "A stakeholder also asked to test <b>hiding pricing</b> (yellow badge). The revenue guardrail will be the judge.", 6500);
  await highlight(page, "#expPanel", false);
  await caption(page, "Nothing launches without a human. <b>Approve launch</b>.", 2500);
  await page.click("text=Approve launch"); log("approved");
  await sleep(1500);
  await caption(page, "Approved. The experiment was just <b>created and started in Statsig</b> through the Console API.", 4500);

  await page.click("#simBtn"); log("traffic");
  await caption(page, "Traffic flows. Users are bucketed per variant; stats run on SingleStore in real time.", 0);
  await page.waitForSelector(".badge.killed", { timeout: 120000 }); log("killed");
  await caption(page, "<b style='color:#ff6b6b'>Guardrail fired.</b> Hiding pricing got more signups but crushed revenue per user, so the agent killed it in Statsig automatically.", 7000);
  await page.waitForSelector("text=Decision memo", { timeout: 240000 }); log("decided");
  await sleep(800);
  await caption(page, "Clear winner (p &lt; 0.01). North Star <b>shipped it in Statsig</b> and wrote the decision memo.", 5500);
  await page.evaluate(() => document.getElementById("memoPanel").scrollIntoView({ behavior: "smooth", block: "center" }));
  await caption(page, "The memo explains the decision with the numbers, and the learnings go into Cognee for the next experiment.", 8000);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await sleep(1200);
  await page.click(".audit .ev.guardrail_kill"); log("audit");
  await caption(page, "Every step is in the <b>audit trail</b>, with the exact data, model output and cost behind it.", 6500);
  await caption(page, "");

  await page.goto(`${BASE}/video/slides.html?s=evidence`); log("evidence");
  await sleep(16000);
  await page.goto(`${BASE}/video/slides.html?s=outro`); log("outro");
  await sleep(8000);

  await ctx.close(); await browser.close();
  log("done");
})().catch((e) => { console.error(e); process.exit(1); });
