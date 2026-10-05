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
    /** Self-running loops, each with its own pause control: the hero, the week, the crossing. */
    loops: 3,
    /** Discrete controls that must be finger-sized. */
    controls: [".how-segment button", ".crossing-switch button", "button[data-copy]", "main summary"],
  },
  {
    path: "/journey",
    headings: [
      en.week.title,
      en.why.title,
      en.trust.title,
      en.integrations.title,
      en.app.title,
      en.selfHost.title,
      en.faq.title,
      en.variants.journey.ending.says,
    ],
    /** The crossing in the hero, and the week. */
    loops: 2,
    controls: [".jc-option", "button[data-copy]", "main summary"],
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
      const controls = variant.controls.map((selector) => page.locator(selector))
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
      for (const avatar of await avatars.all()) await expect(avatar).toHaveAttribute("alt", "")
      // A page may keep portraits for choices not on screen (display: none); the ones shown must load.
      for (const avatar of await page.locator("img.avatar:visible").all()) {
        await avatar.scrollIntoViewIfNeeded()
        await expect.poll(() => avatar.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
      }
      await expect(page.locator(".mock-avatar")).toHaveCount(0)
    })

    test("each trust claim links to the documentation that proves it", async ({ page }) => {
      await page.goto(variant.path)
      // A page may show the claims in its own order, so each link is checked by its claim's title.
      const links = await page
        .locator("#features a.doc-link")
        .evaluateAll((all) => all.map((link) => ({ text: link.textContent ?? "", href: link.getAttribute("href") })))
      expect(links).toHaveLength(TRUST_DOCS.length)
      for (const [index, card] of en.trust.cards.entries()) {
        const link = links.find(({ text }) => text.startsWith(card.title))
        expect(link?.href, card.title).toBe(TRUST_DOCS[index])
      }
    })

    test("its section links stay on the page", async ({ page }) => {
      await page.goto(variant.path)
      const hrefs = await page.locator("nav .nav-wide a").evaluateAll((links) => links.map((link) => link.getAttribute("href")))
      for (const href of hrefs) expect(href).toMatch(new RegExp(`^${variant.path}#`))
      for (const id of hrefs.map((href) => href!.split("#")[1])) await expect(page.locator(`#${id}`)).toHaveCount(1)
    })
  })
}

test("/bold on a phone: the headline, the call to action, and a readable part of the week fit the first screen", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" })
  const page = await context.newPage()
  await page.goto("/bold")
  await expect(page.getByRole("heading", { level: 1 })).toBeInViewport()
  await expect(page.getByRole("link", { name: en.hero.primary }).first()).toBeInViewport()
  const frame = (await page.locator(".reveal-frame").boundingBox())!
  // At least the day names and the morning's events, about 200px of the week, show above the fold.
  expect(844 - frame.y).toBeGreaterThanOrEqual(200)
  // And the whole week is shorter than a screen.
  expect(frame.height).toBeLessThan(844 / 2)
  await context.close()
})

test.describe("/journey", () => {
  const mode = (page: Page, key: string) => page.locator(`label:has(input[name="jc-mode"][value="${key}"])`)
  const landed = (page: Page, option: string) => page.locator(`.jc-landed [data-mode="${option}"]`)

  test("without JavaScript, the hero shows where the Dentist lands, and the switch still works", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto("/journey")
    await expect(landed(page, "busy")).toBeVisible()
    await expect(landed(page, "busy")).toContainText(en.demo.busy)
    await expect(page.locator(".jc-says-land")).toContainText(en.ghost.crossingBusy)
    await mode(page, "details").click()
    await expect(landed(page, "details")).toBeVisible()
    await expect(landed(page, "details")).toContainText(en.demo.events.dentist.title)
    await expect(landed(page, "busy")).toBeHidden()
    await expect(page.locator(".jc-says-land")).toContainText(en.ghost.crossingDetails)
    await context.close()
  })

  test("with reduced motion, a new choice shows its result at once", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/journey")
    await mode(page, "details").click()
    await expect(landed(page, "details")).toBeVisible()
    expect(await landed(page, "details").evaluate((element) => getComputedStyle(element.parentElement!).opacity)).toBe("1")
    await expect(page.locator(".jc")).not.toHaveAttribute("data-moment", /.+/)
    await context.close()
  })

  for (const [option, gone, kept] of [
    ["busy", ["title", "place", "description", "guests", "link"], []],
    ["details", ["guests", "link"], ["title", "place", "description"]],
  ] as const) {
    test(`with ${option === "busy" ? "Busy only" : "details"}, the parts that never cross leave the ghost's copy before it crosses`, async ({ page }) => {
      await page.goto("/journey")
      await mode(page, option).click()
      await expect(page.locator(".jc")).toHaveAttribute("data-moment", "carry", { timeout: 8000 })
      const opacity = (part: string) =>
        page.locator(`.jc-traveler [data-part="${part}"]`).evaluate((element) => Number(getComputedStyle(element).opacity))
      for (const part of gone) expect(await opacity(part), part).toBe(0)
      for (const part of [...kept, "time"]) expect(await opacity(part), part).toBe(1)
    })
  }

  test("pausing the hero stops the ghost where it is", async ({ page }) => {
    await page.goto("/journey")
    await expect(page.locator(".jc")).toHaveAttribute("data-moment", /.+/, { timeout: 10_000 })
    await page.locator(".jc").getByRole("button", { name: en.motion.pause }).click()
    const where = () => page.locator(".jc-ghost").evaluate((element) => element.style.transform)
    const paused = await where()
    await page.waitForTimeout(900)
    expect(await where()).toBe(paused)
  })

  test("on a phone, Sam's calendar sits above Work and the plan is carried down", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const page = await context.newPage()
    await page.goto("/journey")
    const from = (await page.locator(".jc-from").boundingBox())!
    const to = (await page.locator(".jc-to").boundingBox())!
    expect(to.y).toBeGreaterThan(from.y + from.height)
    await page.locator(".jc-to").scrollIntoViewIfNeeded()
    await expect(page.locator(".jc")).toHaveAttribute("data-moment", "carry", { timeout: 12_000 })
    const down = await page.locator(".jc-traveler").evaluate((element) => new DOMMatrix(getComputedStyle(element).transform).m42)
    expect(down).toBeGreaterThan(0)
    await context.close()
  })

  test("the ghost sets the Dentist down at the end as it crossed over in the hero", async ({ page }) => {
    await page.goto("/journey")
    const card = page.locator(".j-end .j-carry-card:visible")
    await expect(card).toHaveCount(1)
    await expect(card).toContainText(en.demo.busy)
    await mode(page, "details").click()
    await expect(page.locator(".j-end .j-carry-card:visible")).toContainText(en.demo.events.dentist.title)
  })

  test("uses its own display face, loaded only here", async ({ page }) => {
    await page.goto("/journey")
    const preloads = await page.locator('link[rel="preload"][as="font"]').evaluateAll((links) => links.map((link) => link.getAttribute("href")))
    expect(preloads.some((href) => href?.includes("young-serif-latin-400-normal"))).toBe(true)
    expect(preloads.some((href) => href?.includes("fraunces"))).toBe(false)
    expect(await page.locator("h1").evaluate((element) => getComputedStyle(element).fontFamily)).toContain("Young Serif")
    await page.goto("/")
    const home = await page.locator('link[rel="preload"][as="font"]').evaluateAll((links) => links.map((link) => link.getAttribute("href")))
    expect(home.some((href) => href?.includes("young-serif"))).toBe(false)
  })

  for (const width of [1440, 1600, 1920]) {
    test(`at ${width}px the travelling ghost rides the margin and never covers the content`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      await page.goto("/journey")
      const carrier = page.locator(".j-rail-carrier")
      const contentLeft = (await page.locator("#features .j-wrap").boundingBox())!.x
      for (const section of ["#how-it-works", "#features", "#integrations", "#self-host"]) {
        await page.locator(section).scrollIntoViewIfNeeded()
        await expect(carrier).toBeVisible()
        const box = (await carrier.boundingBox())!
        expect(box.x).toBeGreaterThanOrEqual(0)
        expect(box.x + box.width).toBeLessThanOrEqual(contentLeft - 8)
      }
      await context.close()
    })
  }

  test("below 1440px there is no margin to ride, so the travelling ghost does not show", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
    const page = await context.newPage()
    await page.goto("/journey")
    await page.locator("#features").scrollIntoViewIfNeeded()
    await expect(page.locator(".j-rail-carrier")).toBeHidden()
    await context.close()
  })

  test("at the last stop the travelling ghost becomes the ending's ghost and sets down what the hero chose", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    await page.goto("/journey")
    await mode(page, "details").click()
    await page.locator("#self-host").scrollIntoViewIfNeeded()
    await expect(page.locator(".j-rail-carrier")).toBeVisible()
    await page.locator(".j-end-scene").scrollIntoViewIfNeeded()
    await expect(page.locator(".journey")).toHaveAttribute("data-delivered", "")
    // One ghost: the margin's hides once the ending's has taken over.
    await expect(page.locator(".j-rail-ghost")).toBeHidden()
    await expect(page.locator(".j-end-scene")).toHaveAttribute("data-awake", "rail")
    const card = page.locator(".j-end .j-carry-card:visible")
    await expect(card).toContainText(en.demo.events.dentist.title)
    await expect.poll(() => page.locator(".j-end-flyer").evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
    await context.close()
  })

  test("with reduced motion the ending is simply landed; without JavaScript it shows Busy and one ghost", async ({ browser }) => {
    const still = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
    const page = await still.newPage()
    await page.goto("/journey")
    await page.locator(".j-end-scene").scrollIntoViewIfNeeded()
    await expect(page.locator(".j-rail-ghost")).toBeHidden()
    expect(await page.locator(".j-end-flyer").evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
    await still.close()

    const plain = await browser.newContext({ viewport: { width: 1440, height: 900 }, javaScriptEnabled: false })
    const noScript = await plain.newPage()
    await noScript.goto("/journey")
    await noScript.locator(".j-end-scene").scrollIntoViewIfNeeded()
    await expect(noScript.locator(".j-rail-carrier")).toBeHidden()
    await expect(noScript.locator(".j-end-flyer")).toBeVisible()
    await expect(noScript.locator(".j-end .j-carry-card:visible")).toContainText(en.demo.busy)
    await plain.close()
  })
})
