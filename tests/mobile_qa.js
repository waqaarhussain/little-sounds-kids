const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:8765/handwriting/", { waitUntil: "networkidle" });
  await page.locator('[data-profile="Child 1"]').click();
  await page.locator("#profileModal").waitFor({ state: "hidden" });
  if ((await page.locator("#siteProfileName").textContent()) !== "CH") throw new Error("Profile initials failed");

  await page.locator('[data-mode="numbers"]').click();
  if ((await page.locator("#numberLevels button").count()) !== 10) throw new Error("Ten number levels were not rendered");
  await page.locator('#numberLevels [data-level="9"]').click();
  if ((await page.locator("#choices button").last().textContent()) !== "100") throw new Error("Number 100 is missing");

  const board = await page.locator(".canvas-wrap").boundingBox();
  if (!board || board.x < 0 || board.x + board.width > 391) throw new Error("Tracing board overflows mobile viewport");
  await page.mouse.move(board.x + 20, board.y + 20);
  await page.mouse.down();
  await page.mouse.move(board.x + 70, board.y + 40);
  await page.mouse.up();
  await page.locator("#check").click();
  if ((await page.locator("#progressText").textContent()).startsWith("1 of")) throw new Error("A small scribble incorrectly passed tracing");

  await page.locator('[data-mode="shapes"]').click();
  const choices = await page.locator("#choices").boundingBox();
  if (!choices || choices.x < 0 || choices.x + choices.width > 391) throw new Error("Shape choices overflow mobile viewport");

  await page.goto("http://127.0.0.1:8765/", { waitUntil: "networkidle" });
  for (const href of ["phonicsbook/", "handwriting/", "counting/", "matching/", "sorting/", "dot-to-dot/", "character-maze/", "character-jigsaw/"]) {
    if ((await page.locator('a[href="' + href + '"]').count()) !== 1) throw new Error("Missing activity " + href);
  }
  console.log("MOBILE QA PASSED: toolbar, initials, 1-100 tracing, scribble rejection, shape layout and activities");
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
