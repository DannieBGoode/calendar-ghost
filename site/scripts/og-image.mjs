// Writes public/og.png from the running preview's hero. Run `npm run preview` first; set
// PREVIEW_PORT when the preview runs on a port other than 4321.
import { chromium } from "@playwright/test"

const port = process.env.PREVIEW_PORT ?? "4321"
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, colorScheme: "dark", reducedMotion: "reduce" })
await page.goto(`http://localhost:${port}/`)
await page.locator(".nav").evaluate((nav) => nav.remove())
await page.screenshot({ path: new URL("../public/og.png", import.meta.url).pathname })
await browser.close()
