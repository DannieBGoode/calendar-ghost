// Writes public/og.png from the running preview's hero. Run `npm run preview` first.
import { chromium } from "@playwright/test"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, colorScheme: "dark", reducedMotion: "reduce" })
await page.goto("http://localhost:4321/")
await page.locator(".nav").evaluate((nav) => nav.remove())
await page.screenshot({ path: new URL("../public/og.png", import.meta.url).pathname })
await browser.close()
