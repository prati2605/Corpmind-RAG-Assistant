/**
 * Walk through the app in headless Chrome and save screenshots (useful for slides and UI review).
 *
 *   CHROME_PATH=/path/to/chrome \
 *   CM_EMPLOYEE=employee.demo@northwind.local CM_ADMIN=admin@yourco.com CM_PASSWORD=... \
 *   node scripts/screenshots.mjs [baseUrl] [outDir]
 *
 * Needs the app running (backend + `npm run preview` or `npm run dev`) with documents loaded.
 * Exits non-zero if the page throws an error.
 */
import fs from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.argv[2] || "http://localhost:4173";
const OUT = process.argv[3] || "screenshots";
const { CHROME_PATH, CM_EMPLOYEE, CM_ADMIN, CM_PASSWORD, CM_ADMIN_PASSWORD } = process.env;
if (!CHROME_PATH || !CM_EMPLOYEE || !CM_ADMIN || !CM_PASSWORD) {
  console.error("Set CHROME_PATH, CM_EMPLOYEE, CM_ADMIN and CM_PASSWORD (and CM_ADMIN_PASSWORD if different).");
  process.exit(2);
}
fs.mkdirSync(OUT, { recursive: true });
const browser = await puppeteer.launch({ executablePath: CHROME_PATH, headless: true, args: ["--no-sandbox"] });
const pageErrors = [];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = (p, name) => p.screenshot({ path: `${OUT}/${name}.png` });

async function session(email, password, width = 1440, height = 900) {
  const p = await (await browser.createBrowserContext()).newPage();
  await p.setViewport({ width, height });
  p.on("pageerror", (e) => pageErrors.push(e.message));
  await p.goto(BASE + "/login", { waitUntil: "networkidle0" });
  await p.type("#email", email);
  await p.type("#password", password);
  await Promise.all([p.click("button[type=submit]"), p.waitForNavigation({ waitUntil: "networkidle0" })]);
  return p;
}
async function ask(p, q) {
  const before = (await p.$$("button[aria-label^='Source ']")).length;
  await p.type("textarea", q);
  await p.keyboard.press("Enter");
  await p.waitForFunction((n) => document.querySelectorAll("[aria-live=polite] .typing").length === 0 &&
    document.querySelectorAll("ol > li").length > 0, { timeout: 60000 }, before);
  await wait(600);
}

const login = await (await browser.createBrowserContext()).newPage();
await login.setViewport({ width: 1440, height: 900 });
await login.goto(BASE + "/login", { waitUntil: "networkidle0" });
await shot(login, "01-sign-in");

const e = await session(CM_EMPLOYEE, CM_PASSWORD);
await shot(e, "02-overview");
await e.goto(BASE + "/chat", { waitUntil: "networkidle0" });
await shot(e, "03-ask-empty");
await ask(e, "How many unused leave days can I carry forward, and when do they expire?");
await ask(e, "What is the hotel limit per night in a metro city?");
await ask(e, "What is the dress code for the annual gala?");
await shot(e, "04-answers");
const marker = await e.$("button[aria-label^='Source 1']");
if (marker) {
  await marker.click();
  await wait(1200);
  await shot(e, "05-source");
}
for (const [path, name] of [["/documents", "06-documents"], ["/history", "07-history"], ["/settings", "08-settings"]]) {
  await e.goto(BASE + path, { waitUntil: "networkidle0" });
  await shot(e, name);
}

const a = await session(CM_ADMIN, CM_ADMIN_PASSWORD || CM_PASSWORD);
await a.goto(BASE + "/documents", { waitUntil: "networkidle0" });
await shot(a, "09-documents-admin");
for (const tab of ["users", "access", "analytics", "feedback", "audit"]) {
  await a.goto(`${BASE}/admin?tab=${tab}`, { waitUntil: "networkidle0" });
  await wait(300);
  await shot(a, `10-admin-${tab}`);
}

const m = await session(CM_EMPLOYEE, CM_PASSWORD, 390, 844);
await m.goto(BASE + "/chat", { waitUntil: "networkidle0" });
await shot(m, "11-mobile-ask");

await browser.close();
console.log(`Saved screenshots to ${OUT}/`);
if (pageErrors.length) {
  console.error("Page errors:", pageErrors);
  process.exit(1);
}
