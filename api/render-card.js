// api/render-card.js
// Screenshots the HMAC-signed /render/card/{id} page and returns a PNG.
// Runs as a separate Vercel Node function so headless Chromium never bloats
// the Python app bundle. Only math-heavy cards are routed here by the bot.

const crypto = require("crypto");
const chromium = require("@sparticuz/chromium");
const puppeteer = require("puppeteer-core");

const RENDER_WIDTH = 720;
const PAGE_TIMEOUT_MS = 9000;

// Mirrors render_auth.py — keep the two in sync.
function validSignature(cardId, exp, sig) {
  const secret = process.env.SECRET_KEY;
  if (!secret) return false;
  if (!/^\d+$/.test(cardId || "") || !/^\d+$/.test(exp || "") || !/^[0-9a-f]{64}$/.test(sig || "")) return false;
  if (Number(exp) < Date.now() / 1000) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`render-card:${cardId}:${exp}`)
    .digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig));
}

module.exports = async (req, res) => {
  const { card_id: cardId, exp, sig } = req.query;
  if (!validSignature(cardId, exp, sig)) {
    res.status(403).json({ error: "Invalid or expired signature" });
    return;
  }

  const appUrl = (process.env.APP_URL || "").replace(/\/$/, "");
  if (!appUrl) {
    res.status(503).json({ error: "APP_URL is not configured" });
    return;
  }

  let browser;
  try {
    browser = await puppeteer.launch({
      args: chromium.args,
      defaultViewport: { width: RENDER_WIDTH, height: 800, deviceScaleFactor: 2 },
      // CHROME_EXECUTABLE_PATH allows running against a local Chrome in dev.
      executablePath: process.env.CHROME_EXECUTABLE_PATH || (await chromium.executablePath()),
      headless: chromium.headless,
    });
    const page = await browser.newPage();
    await page.goto(`${appUrl}/render/card/${cardId}?exp=${exp}&sig=${sig}`, {
      waitUntil: "domcontentloaded",
      timeout: PAGE_TIMEOUT_MS,
    });
    // Set by the page once markdown is injected and MathJax has typeset.
    await page.waitForFunction("window.__RENDER_READY__ === true", { timeout: PAGE_TIMEOUT_MS });
    const card = await page.$("#card");
    const png = await card.screenshot({ type: "png" });

    res.setHeader("Content-Type", "image/png");
    res.setHeader("Cache-Control", "no-store");
    res.status(200).send(png);
  } catch (error) {
    console.error("render-card failed:", error);
    res.status(500).json({ error: "Failed to render card" });
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
  }
};
