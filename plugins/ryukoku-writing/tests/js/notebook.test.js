// Headless-browser check of the evidence notebook (Playwright, Chromium). Called by tests/test_notebook.py:
//   node tests/js/notebook.test.js <url> <passphrase>
// It plays the student: open the proposals tab, confirm a decision cannot be chosen before "Show", show the diff,
// choose "accept", add it to the list, sign with the passphrase once, and check the status line and the empty list.
"use strict";
const { chromium } = require("playwright");
const assert = require("assert");
(async () => {
  const [url, pass] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(url);
  await page.click("#t-proposals");
  const item = page.locator("#proposals .item").first();
  await item.waitFor();
  assert.strictEqual(await item.locator("select.dec").count(), 0, "no decision control before the content is shown");
  assert.strictEqual(await page.locator("#signBtn").isDisabled(), true);
  await item.locator("button.show").click();
  await item.locator(".diff .ins").first().waitFor();
  await item.locator("select.dec").selectOption("accepted");
  await item.locator("button.add").click();
  assert.strictEqual(await page.locator("#basketList li").count(), 1);
  await page.click("#signBtn");
  await page.fill("#pw", pass);
  await page.click("#dlgOk");
  await page.waitForFunction(() => /署名した|Signed/.test(document.getElementById("status").textContent), null, { timeout: 60000 });
  assert.strictEqual(await page.locator("#pw").inputValue(), "", "the passphrase field is cleared");
  assert.ok((await page.locator("#basketList").textContent()).includes("なし") || (await page.locator("#basketList").textContent()).includes("none"));
  // keyboard: tabs move with the arrow keys
  await page.focus("#t-overview");
  await page.keyboard.press("ArrowRight");
  assert.strictEqual(await page.evaluate(() => document.activeElement.id), "t-research");
  assert.deepStrictEqual(errors, []);
  await browser.close();
  console.log("notebook browser test: ok");
})().catch((e) => { console.error(e); process.exit(1); });
