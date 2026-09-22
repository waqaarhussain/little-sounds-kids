const { chromium } = require("playwright");

const games = {
  rescue: "rescue-world",
  kart: "kart-racing",
  runner: "rescue-runner",
  academy: "training-academy",
  cafe: "pet-cafe",
  dance: "dance-party",
  hide: "hide-and-seek"
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });

  await page.route("**/api/profile", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ profile: "Nevaeh", profiles: ["Parent", "Nevaeh", "Inaara"], parent_profile: "Parent", child_profiles: ["Nevaeh", "Inaara"] }) }));
  await page.route("**/api/activity/variant?**", route => {
    const url = new URL(route.request().url());
    const activity = url.searchParams.get("activity");
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      activity, attempt: 1,
      plan: {
        layout_version: 1, seed: 748392, world: "Rainbow City", mission_number: 1,
        themes: ["bluey", "paw-patrol"], theme_labels: ["Bluey", "Paw Patrol"], sticker_ids: [1, 2],
        characters: [
          { sticker_id: 1, theme: "bluey", theme_label: "Bluey", image: "/icons/app-icon-192.png", serial: 1 },
          { sticker_id: 2, theme: "paw-patrol", theme_label: "Paw Patrol", image: "/icons/app-icon-512.png", serial: 1 }
        ]
      }
    }) });
  });

  await page.goto("http://127.0.0.1:8765/games/", { waitUntil: "networkidle" });
  if (await page.locator(".pack-card").count() !== 7) throw new Error("The game hub does not show all seven games");
  if (await page.locator('a[href^="play/?game="]').count() !== 7) throw new Error("The game hub links are incomplete");

  for (const [game, activity] of Object.entries(games)) {
    await page.goto(`http://127.0.0.1:8765/games/play/?game=${game}`, { waitUntil: "networkidle" });
    await page.locator("#startGame").waitFor({ state: "visible" });
    if (await page.locator(".team-character").count() !== 2) throw new Error(`${game} did not load two characters`);
    if (await page.locator("body").getAttribute("data-progress-activity") !== activity) throw new Error(`${game} has the wrong reward activity`);
    await page.locator("#startGame").click();
    await page.waitForTimeout(180);
    const box = await page.locator("#gameFrame").boundingBox();
    if (!box || box.x < 0 || box.x + box.width > 1025) throw new Error(`${game} overflows the iPad viewport`);
    if (await page.locator("#touchControls button").count() === 0 && !["academy"].includes(game)) throw new Error(`${game} has no touch controls`);
    if (await page.locator("#hud").isHidden()) throw new Error(`${game} did not start its HUD`);
  }

  if (errors.length) throw new Error("Browser errors: " + errors.join(" | "));
  console.log("GAME PACK BROWSER QA PASSED: hub and seven iPad game canvases");
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
