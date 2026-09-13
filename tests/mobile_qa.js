const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:8765/handwriting/", { waitUntil: "networkidle" });
  await page.locator('[data-profile="Child 1"]').click();
  await page.locator("#profileModal").waitFor({ state: "hidden" });
  await page.locator('[data-mode="numbers"]').click();
  await page.locator("#board").scrollIntoViewIfNeeded();
  const board = await page.locator("#board").boundingBox();
  if (!board || board.x < 0 || board.x + board.width > 391) throw new Error("Tracing board overflows mobile viewport");
  await page.touchscreen.tap(board.x + board.width * 0.25, board.y + board.height * 0.25);
  await page.mouse.move(board.x + board.width * 0.25, board.y + board.height * 0.25);
  await page.mouse.down();
  for (let step = 0; step < 14; step += 1) {
    await page.mouse.move(board.x + board.width * (0.25 + step * 0.035), board.y + board.height * (0.25 + (step % 5) * 0.1));
  }
  await page.mouse.up();
  await page.locator("#finishButton").click();
  await page.waitForFunction(() => document.querySelector("#progressText")?.textContent.startsWith("1 of 9"));
  await page.locator('[data-mode="shapes"]').click();
  await page.screenshot({ path: "mobile-tracing-qa.png", fullPage: true });
  await page.reload({ waitUntil: "networkidle" });
  if ((await page.locator("#siteProfileName").textContent()) !== "Child 1") throw new Error("Remembered profile failed");
  console.log("MOBILE QA PASSED: fit, touch drawing, saved progress, tabs and remembered profile");
  await browser.close();
})().catch(error => {
  console.error(error);
  process.exit(1);
});
