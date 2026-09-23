"use strict";

// Optional real-browser check. The Python product and unit suite remain
// standard-library only; this script requires an existing Playwright package
// and Chrome installation for the browser observation.
const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.G5_CHROME ||
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  const page = await browser.newPage({ viewport: { width: 650, height: 800 } });
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  try {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(process.env.G5_BROWSER_URL || "http://127.0.0.1:18765/");
    assert.equal(await page.title(), "合成能耗批次台账");
    assert.match(await page.locator("body").innerText(), /合成能耗批次台账/);

    const filename = path.join(__dirname, "..", "fixtures", "G2-valid.csv");
    await page.locator("#csv-file").setInputFiles(filename);
    await page.locator("#dataset-id").fill("");
    await page.locator("#submit-import").click();
    assert.equal(await page.locator("#dataset-id").getAttribute("aria-invalid"), "true");
    assert.equal(await page.evaluate(() => document.activeElement.id), "dataset-id");
    assert.match(await page.locator("#notice").innerText(), /数据集 ID/);
    assert.match(await page.locator("#dataset-id").getAttribute("aria-describedby"), /notice/);

    const datasetId = `g5-browser-${Date.now()}`;
    await page.locator("#dataset-id").fill(datasetId);
    assert.equal(await page.locator("#dataset-id").getAttribute("aria-describedby"), "dataset-id-hint");
    await page.locator("#csv-file").setInputFiles([]);
    await page.locator("#submit-import").click();
    assert.equal(await page.locator("#csv-file").getAttribute("aria-invalid"), "true");
    assert.equal(await page.evaluate(() => document.activeElement.id), "csv-file");
    assert.match(await page.locator("#csv-file").getAttribute("aria-describedby"), /notice/);
    await page.locator("#csv-file").setInputFiles(filename);
    assert.equal(await page.locator("#csv-file").getAttribute("aria-describedby"), "csv-file-hint");
    await page.evaluate(() => {
      window.__scrollOptions = null;
      document.getElementById("result").scrollIntoView = (options) => {
        window.__scrollOptions = options;
      };
    });
    await page.locator("#submit-import").click();
    await page.getByText(`已接受 ${datasetId}`).waitFor();
    assert.equal(await page.locator("#dataset-id").getAttribute("aria-invalid"), null);
    assert.equal(await page.evaluate(() => document.activeElement.id), "result-title");
    assert.equal(await page.evaluate(() => window.__scrollOptions?.behavior), "auto");
    assert.match(await page.locator("#monthly-totals").innerText(), /300\.000 kWh/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);

    let tableReachedByTab = false;
    for (let index = 0; index < 6; index += 1) {
      await page.keyboard.press("Tab");
      if (await page.evaluate(() => document.activeElement.id) === "comparison-table-wrap") {
        tableReachedByTab = true;
        break;
      }
    }
    assert.equal(tableReachedByTab, true);
    const table = page.locator("#comparison-table-wrap");
    assert.equal(await table.evaluate((element) => element.scrollWidth > element.clientWidth), true);
    const beforeScroll = await table.evaluate((element) => element.scrollLeft);
    await page.keyboard.press("ArrowRight");
    const afterScroll = await table.evaluate((element) => element.scrollLeft);
    assert.ok(afterScroll > beforeScroll);
    assert.equal(await table.evaluate((element) => getComputedStyle(element).outlineStyle === "none"), false);

    await page.locator("#history").click();
    await page.getByRole("button", { name: datasetId }).click();
    await page.getByText(`已从不可变台账读取 ${datasetId}`).waitFor();
    assert.equal(await page.evaluate(() => document.activeElement.id), "result-title");
    assert.match(await page.locator("#monthly-totals").innerText(), /370\.000 kWh/);
    assert.equal(await table.evaluate((element) => element.scrollLeft), 0);
    assert.deepEqual(errors, []);
    const screenshots = [];
    if (process.env.G5_SCREENSHOT_DIR) {
      const narrow = path.join(process.env.G5_SCREENSHOT_DIR, "g5-expand-narrow.png");
      await page.screenshot({ path: narrow, fullPage: true });
      screenshots.push(narrow);
      await page.setViewportSize({ width: 1200, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      const desktop = path.join(process.env.G5_SCREENSHOT_DIR, "g5-expand-desktop.png");
      await page.screenshot({ path: desktop, fullPage: true });
      screenshots.push(desktop);
    }
    console.log(JSON.stringify({ status: "PASS", dataset_id: datasetId, table_scroll: [beforeScroll, afterScroll], console_errors: errors, screenshots }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
