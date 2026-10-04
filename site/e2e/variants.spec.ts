import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"
import { TRUST_DOCS } from "../src/links"

/** The alternative page designs, each with the headings a visitor must find without JavaScript. */
const VARIANTS = [
  {
    path: "/bold",
    headings: [
      en.how.title,
      en.week.title,
      en.crossing.title,
      en.app.title,
      en.trust.title,
      en.integrations.title,
      en.selfHost.title,
      en.why.title,
      en.faq.title,
      en.variants.bold.footer.cta,
    ],
    /** Self-running loops, each with its own pause control: the hero, the week, the crossing, the proofs. */
    loops: 4,
  },
]

/** Scrolls through the whole page so every island hydrates and every once-only scene wakes. */
async function visitEverything(page: Page) {
  const height = await page.evaluate(() => document.body.scrollHeight)
  for (let top = 0; top < height; top += 400) {
    await page.evaluate((y) => window.scrollTo(0, y), top)
    await page.waitForTimeout(60)
  }
}

/** Every CSS animation on the page, with whether a pause control governs it. */
function animations(page: Page) {
  return page.evaluate(() =>
    document.getAnimations().map((animation) => {
      const effect = animation.effect as KeyframeEffect | null
      const target = effect?.target as Element | null
      return {
        name: (animation as CSSAnimation).animationName ?? "transition",
        state: animation.playState,
        endTime: Number(effect?.getComputedTiming().endTime ?? 0),
        governed: Boolean(target?.closest("[data-playing]")),
      }
    }),
  )
}

for (const variant of VARIANTS) {
  test.describe(variant.path, () => {
    test("loads nothing from another host", async ({ page, baseURL }) => {
      const foreign: string[] = []
      const host = new URL(baseURL!).host
      page.on("request", (request) => {
        if (new URL(request.url()).host !== host) foreign.push(request.url())
      })
      await page.goto(variant.path)
      await visitEverything(page)
      await page.waitForLoadState("networkidle")
      expect(foreign).toEqual([])
    })

    test("is not indexed and stays out of the sitemap", async ({ page, request }) => {
      await page.goto(variant.path)
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex")
      const sitemap = await (await request.get("/sitemap-0.xml")).text()
      expect(sitemap).toContain("<loc>https://calendarghost.com/</loc>")
      expect(sitemap).not.toContain(variant.path)
    })

    for (const width of [320, 390]) {
      test(`nothing scrolls sideways on a ${width}px screen`, async ({ browser }) => {
        const context = await browser.newContext({ viewport: { width, height: 740 } })
        const page = await context.newPage()
        await page.goto(variant.path)
        await visitEverything(page)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
        await context.close()
      })
    }

    test("with reduced motion, nothing moves by itself", async ({ browser }) => {
      const context = await browser.newContext({ reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto(variant.path)
      await visitEverything(page)
      await page.waitForTimeout(400)
      const running = (await animations(page)).filter((animation) => animation.state === "running")
      expect(running).toEqual([])
      const split = () => page.locator(".reveal-frame").evaluate((frame) => getComputedStyle(frame).getPropertyValue("--split").trim())
      expect(await split()).toBe("55%")
      await page.waitForTimeout(1000)
      expect(await split()).toBe("55%")
      await expect(page.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
      await context.close()
    })

    test("without JavaScript, the headline and every section heading are there", async ({ browser }) => {
      const context = await browser.newContext({ javaScriptEnabled: false })
      const page = await context.newPage()
      await page.goto(variant.path)
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.hero.title)
      for (const heading of variant.headings) {
        await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible()
      }
      await expect(page.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
      await context.close()
    })

    test("every loop has a pause control a finger can hit, and pausing stops it", async ({ page }) => {
      await page.goto(variant.path)
      await visitEverything(page)
      const buttons = page.getByRole("button", { name: en.motion.pause })
      await expect(buttons).toHaveCount(variant.loops)
      for (const button of await buttons.all()) {
        expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      }
      // Motion with no pause control must stop by itself within five seconds (WCAG 2.2.2).
      for (const animation of await animations(page)) {
        if (!animation.governed) expect(animation.endTime, animation.name).toBeLessThanOrEqual(5000)
      }
      // Each click turns a Pause button into Play, so the first Pause left is always the next one.
      for (let loop = 0; loop < variant.loops; loop += 1) {
        await buttons.first().scrollIntoViewIfNeeded()
        await buttons.first().click()
      }
      await expect(page.getByRole("button", { name: en.motion.play })).toHaveCount(variant.loops)
      const endless = (await animations(page)).filter((animation) => animation.endTime === Infinity)
      expect(endless.length).toBeGreaterThan(0)
      for (const animation of endless) expect(animation.state, animation.name).toBe("paused")
    })

    test("small controls are at least 44px tall", async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
      const page = await context.newPage()
      await page.goto(variant.path)
      await visitEverything(page)
      const controls = [page.locator(".crossing-switch button"), page.locator("button[data-copy]"), page.locator("main summary")]
      for (const control of controls) {
        await expect(control.first()).toBeVisible()
        for (const item of await control.all()) expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      }
      await context.close()
    })

    test("calendars show Sam's portraits, never letters", async ({ page }) => {
      await page.goto(variant.path)
      await visitEverything(page)
      const avatars = page.locator("img.avatar")
      expect(await avatars.count()).toBeGreaterThan(0)
      for (const avatar of await avatars.all()) {
        await avatar.scrollIntoViewIfNeeded()
        await expect(avatar).toHaveAttribute("alt", "")
        await expect.poll(() => avatar.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
      }
      await expect(page.locator(".mock-avatar")).toHaveCount(0)
    })

    test("each trust claim links to the documentation that proves it", async ({ page }) => {
      await page.goto(variant.path)
      const hrefs = await page.locator("#features a.doc-link").evaluateAll((all) => all.map((link) => link.getAttribute("href")))
      expect(hrefs).toEqual([...TRUST_DOCS])
    })

    test("its section links stay on the page", async ({ page }) => {
      await page.goto(variant.path)
      const hrefs = await page.locator("nav .nav-wide a").evaluateAll((links) => links.map((link) => link.getAttribute("href")))
      for (const href of hrefs) expect(href).toMatch(new RegExp(`^${variant.path}#`))
      for (const id of hrefs.map((href) => href!.split("#")[1])) await expect(page.locator(`#${id}`)).toHaveCount(1)
    })
  })
}
