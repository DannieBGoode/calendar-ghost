import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"
import { TRUST_DOCS } from "../src/links"
import { NON_PRODUCTION_PATHS, STATUS_LABELS, VERSIONS, VERSIONS_LINK_LABEL, VERSIONS_PATH } from "../src/versions"

/** The home page's sections, whose headings every home hero iteration keeps. */
const HOME_HEADINGS = [
  en.how.title,
  en.week.title,
  en.crossing.title,
  en.app.title,
  en.trust.title,
  en.integrations.title,
  en.selfHost.title,
  en.why.title,
  en.faq.title,
  en.footer.cta,
]
const HOME_CONTROLS = [".how-segment button", ".crossing-switch button", "button[data-copy]", "main summary"]

/**
 * The alternative page designs, each with the headings a visitor must find without JavaScript.
 * `title` is the headline's accessible name; `rest` is where a Wide Reveal on the page rests
 * (null when it has none).
 */
const VARIANTS = [
  {
    path: "/bold",
    title: en.hero.title,
    rest: "55%",
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
      en.variants.bold.footer.lines.join(" "),
    ],
    /** Self-running loops, each with its own pause control: the hero, the week, the crossing. */
    loops: 3,
    /** Discrete controls that must be finger-sized. */
    controls: [".how-segment button", ".crossing-switch button", "button[data-copy]", "main summary"],
  },
  {
    path: "/journey",
    title: en.hero.title,
    rest: "55%",
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
  {
    path: "/home/hero-a",
    title: en.hero.title,
    rest: "40%",
    headings: HOME_HEADINGS,
    /** The hero, the week, the crossing. */
    loops: 3,
    controls: HOME_CONTROLS,
  },
  {
    path: "/home/hero-b",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's crossing, the week, the home page's crossing. */
    loops: 3,
    controls: [".jc-option", ...HOME_CONTROLS],
  },
  {
    path: "/home/hero-a2",
    title: en.hero.title,
    rest: "40%",
    headings: HOME_HEADINGS,
    /** The hero, the week, the crossing. */
    loops: 3,
    controls: HOME_CONTROLS,
  },
  {
    path: "/home/hero-b2",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's crossing (it plays once, then on request), the week, the home page's crossing. */
    loops: 3,
    controls: [".jc-option", ...HOME_CONTROLS],
  },
  {
    path: "/home/hero-c",
    title: en.variants.homeHeroes.c.title,
    rest: "50%",
    headings: HOME_HEADINGS,
    /** The headline, the two-day strip, the week, the crossing. */
    loops: 4,
    controls: HOME_CONTROLS,
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
      if (variant.rest) {
        const split = () => page.locator(".reveal-frame").evaluate((frame) => getComputedStyle(frame).getPropertyValue("--split").trim())
        expect(await split()).toBe(variant.rest)
        await page.waitForTimeout(1000)
        expect(await split()).toBe(variant.rest)
      }
      await expect(page.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
      await context.close()
    })

    test("without JavaScript, the headline and every section heading are there", async ({ browser }) => {
      const context = await browser.newContext({ javaScriptEnabled: false })
      const page = await context.newPage()
      await page.goto(variant.path)
      await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName(variant.title)
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
        .locator("#trust a.doc-link")
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
      const contentLeft = (await page.locator("#trust .j-wrap").boundingBox())!.x
      for (const section of ["#how-it-works", "#trust", "#features", "#integrations", "#self-host"]) {
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

/** The home hero iterations: what each one's first screen must show at a laptop's size. */
const HOME_HEROES = [
  {
    path: "/home/hero-a",
    /** The demo's point: what work sees, beside the divider. */
    point: ".hh-a .reveal-frame",
  },
  {
    path: "/home/hero-b",
    /** Where the Dentist lands on Work: Busy, 15:00 to 16:30. */
    point: '.jc-landed [data-mode="busy"]',
  },
  {
    path: "/home/hero-a2",
    /** The week, inside the page's width. */
    point: ".hh-a2 .reveal-frame",
  },
  {
    path: "/home/hero-b2",
    /** Where the Dentist lands on Work: Busy, 15:00 to 16:30. */
    point: '.jc-landed [data-mode="busy"]',
  },
  {
    path: "/home/hero-c",
    /** The proof under the headline: two days of what Sam sees against what work sees. */
    point: ".hh-c-proof .reveal-frame",
  },
]

test.describe("home hero iterations", () => {
  for (const hero of HOME_HEROES) {
    for (const [width, height] of [
      [1280, 800],
      [1024, 768],
    ] as const) {
      test(`${hero.path} at ${width}x${height}: the headline, the line, the calls to action, and the demo's point fit the first screen`, async ({ browser }) => {
        const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
        const page = await context.newPage()
        await page.goto(hero.path)
        const fits = async (selector: string) => {
          const box = (await page.locator(selector).first().boundingBox())!
          expect(box.y, selector).toBeGreaterThanOrEqual(0)
          expect(box.y + box.height, selector).toBeLessThanOrEqual(height)
        }
        for (const selector of ["h1", ".hh-line", ".hh-ctas", ".hh-meta", hero.point]) await fits(selector)
        await expect(page.locator(".hh-line")).toHaveText(en.variants.homeHeroes.line)
        await expect(page.locator(".hh-meta")).toHaveText(en.variants.homeHeroes.meta)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
        await context.close()
      })
    }

    test(`${hero.path}: the hero's ghost is never the green one`, async ({ page }) => {
      await page.goto(hero.path)
      await expect(page.locator(".hh .ghost").first()).toBeAttached()
      await expect(page.locator('.hh .ghost[data-tone="moss"]')).toHaveCount(0)
    })
  }

  test("/home/hero-a sweeps left first, so Busy fills the frame within 2.5 seconds", async ({ page }) => {
    await page.goto("/home/hero-a")
    const split = () =>
      page.locator(".reveal-frame").evaluate((frame) => Number.parseFloat(getComputedStyle(frame).getPropertyValue("--split")))
    await expect.poll(split, { timeout: 2500 }).toBeLessThan(25)
  })

  test("/home/hero-a pins its labels to the divider and keeps its pause control in the frame's corner", async ({ page }) => {
    await page.goto("/home/hero-a")
    const slider = page.getByRole("slider", { name: en.demo.sliderLabel })
    await slider.focus()
    await slider.fill("50")
    const frame = (await page.locator(".reveal-frame").boundingBox())!
    const divider = (await page.locator(".reveal-divider").boundingBox())!
    const you = (await page.locator(".reveal-pin-you").boundingBox())!
    const work = (await page.locator(".reveal-pin-work").boundingBox())!
    expect(divider.x - (you.x + you.width)).toBeGreaterThan(0)
    expect(divider.x - (you.x + you.width)).toBeLessThan(16)
    expect(work.x - (divider.x + divider.width)).toBeGreaterThan(0)
    expect(work.x - (divider.x + divider.width)).toBeLessThan(16)
    await expect(page.locator(".reveal-pin-you")).toHaveText(en.demo.youSee)
    await expect(page.locator(".reveal-pin-work")).toHaveText(en.demo.workSees)
    const pause = page.locator(".reveal-frame").getByRole("button", { name: en.motion.pause })
    const button = (await pause.boundingBox())!
    expect(button.height).toBeGreaterThanOrEqual(44)
    expect(button.width).toBeGreaterThanOrEqual(44)
    expect(button.y).toBeLessThanOrEqual(frame.y + 1)
    expect(Math.min(frame.x + frame.width, 1280) - (button.x + button.width)).toBeLessThanOrEqual(1)
  })

  test("/home/hero-a's hint says to move a mouse, or to drag on a touch screen", async ({ browser }) => {
    const desktop = await browser.newContext()
    const page = await desktop.newPage()
    await page.goto("/home/hero-a")
    await expect(page.getByText(en.variants.homeHeroes.handleHint.mouse)).toBeVisible()
    await expect(page.getByText(en.variants.homeHeroes.handleHint.touch)).toBeHidden()
    await desktop.close()
    const touch = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })
    const phone = await touch.newPage()
    await phone.goto("/home/hero-a")
    await expect(phone.getByText(en.variants.homeHeroes.handleHint.touch)).toBeVisible()
    await expect(phone.getByText(en.variants.homeHeroes.handleHint.mouse)).toBeHidden()
    await touch.close()
  })

  test("/home/hero-b without JavaScript: the Dentist has landed on Work as Busy, and its guest and link stayed with Sam", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto("/home/hero-b")
    const landed = page.locator('.jc-landed [data-mode="busy"]')
    await expect(landed).toBeVisible()
    await expect(landed).toContainText(en.demo.busy)
    await expect(landed).toContainText("15:00–16:30")
    await expect(page.locator(".jc-from")).toContainText(en.crossing.guests)
    await expect(page.locator(".jc-from")).toContainText(en.crossing.link)
    await expect(page.locator(".jc-to")).not.toContainText(en.crossing.guests)
    await context.close()
  })

  test("/home/hero-b starts carrying within two seconds", async ({ page }) => {
    await page.goto("/home/hero-b")
    // It rests on the landed result first, then flies back to fetch the Dentist.
    await expect(page.locator(".jc")).toHaveAttribute("data-moment", "fetch", { timeout: 2000 })
  })

  for (const width of [390, 1024, 1280, 1440]) {
    test(`/home/hero-a2 at ${width}px keeps its week and its pause control inside the page`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      await page.goto("/home/hero-a2")
      const frame = (await page.locator(".hh-a2 .reveal-frame").boundingBox())!
      expect(frame.x).toBeGreaterThanOrEqual(0)
      expect(frame.x + frame.width).toBeLessThanOrEqual(width)
      const pause = page.locator(".hh-a2 .reveal-frame").getByRole("button", { name: en.motion.pause })
      const button = (await pause.boundingBox())!
      expect(button.height).toBeGreaterThanOrEqual(44)
      expect(button.x).toBeGreaterThanOrEqual(frame.x)
      expect(button.x + button.width).toBeLessThanOrEqual(Math.min(width, frame.x + frame.width) + 1)
      await context.close()
    })
  }

  test("/home/hero-a2 shows a calmer week: one work meeting, two plans as Busy, a plain Busy fill", async ({ page }) => {
    await page.goto("/home/hero-a2")
    const you = page.locator(".hh-a2 .reveal-you .cal-event")
    await expect(you).toHaveCount(3)
    await expect(you).toHaveText([
      new RegExp(en.demo.events.standup.title),
      new RegExp(en.demo.events.dentist.title),
      new RegExp(en.demo.events.gym.title),
    ])
    const busy = page.locator(".hh-a2 .reveal-work .cal-event.is-busy")
    await expect(busy).toHaveCount(2)
    for (const block of await busy.all()) {
      await expect(block).toHaveText(en.demo.busy)
      expect(await block.evaluate((element) => getComputedStyle(element).backgroundImage)).toBe("none")
    }
  })

  test("/home/hero-a2's hint goes for good once the visitor has held the ghost", async ({ page }) => {
    await page.goto("/home/hero-a2")
    const hint = page.locator(".hh-a2 .reveal-handle-hint")
    await expect(hint).toHaveCSS("opacity", "1")
    const slider = page.getByRole("slider", { name: en.demo.sliderLabel })
    await slider.focus()
    await slider.blur()
    await expect(page.locator(".hh-a2 .reveal-frame")).toHaveAttribute("data-touched", "")
    await expect(hint).toHaveCSS("opacity", "0")
  })

  test("/home/hero-b2 without JavaScript: Busy has landed, the guest and link stayed home, and nobody speaks", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto("/home/hero-b2")
    const landed = page.locator('.hh-b2 .jc-landed [data-mode="busy"]')
    await expect(landed).toBeVisible()
    await expect(landed).toContainText(en.demo.busy)
    await expect(landed).toContainText("15:00–16:30")
    const card = page.locator(".hh-b2 .jc-from")
    await expect(card).toContainText(en.demo.events.dentist.detail)
    await expect(card).toContainText(en.crossing.guests)
    await expect(card).toContainText(en.crossing.link)
    await expect(card).not.toContainText(en.variants.journey.crossing.description)
    await expect(page.locator(".hh-b2 .jc-to")).not.toContainText(en.crossing.guests)
    // Work shows only the hours around the Dentist.
    await expect(page.locator(".hh-b2 .jc-hour")).toHaveText(["14:00", "15:00", "16:00"])
    await expect(page.locator(".hh .speech-bubble")).toHaveCount(0)
    // The switch's heading and its sentence are there for screen readers, not on screen.
    await expect(page.locator(".hh-b2").getByRole("group", { name: en.crossing.switchLabel })).toBeAttached()
    await expect(page.locator(".hh-b2 .jc-explain")).toHaveCSS("position", "absolute")
    await context.close()
  })

  test("/home/hero-b2 carries the Dentist once, rests on Busy, and carries it again when a pointer comes over it", async ({ page }) => {
    await page.goto("/home/hero-b2")
    const crossing = page.locator(".hh-b2 .jc")
    await expect(crossing).toHaveAttribute("data-moment", "fetch", { timeout: 2500 })
    await expect(crossing).toHaveAttribute("data-moment", "carry", { timeout: 6000 })
    await expect(crossing).not.toHaveAttribute("data-moment", /.+/, { timeout: 6000 })
    await expect(page.locator('.hh-b2 .jc-landed [data-mode="busy"]')).toBeVisible()
    // It rests: no second run by itself.
    await page.waitForTimeout(3000)
    await expect(crossing).not.toHaveAttribute("data-moment", /.+/)
    await page.locator(".hh-b2 .jc-to").hover()
    await expect(crossing).toHaveAttribute("data-moment", "fetch", { timeout: 1000 })
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`/home/hero-b2 in ${scheme}: a ghost 56 to 72px wide, ${scheme === "light" ? "outlined, with no halo" : "white and glowing"}`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme })
      const page = await context.newPage()
      await page.goto("/home/hero-b2")
      const ghost = page.locator(".hh-b2 .jc-ghost")
      const box = (await ghost.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(56)
      expect(box.width).toBeLessThanOrEqual(72)
      const glow = await page
        .locator(".hh-b2 .jc-ghost .ghost")
        .first()
        .evaluate((element) => getComputedStyle(element, "::before").backgroundColor)
      if (scheme === "light") expect(glow).toBe("rgba(0, 0, 0, 0)")
      else expect(glow).not.toBe("rgba(0, 0, 0, 0)")
      await context.close()
    })
  }

  test("/home/hero-b2 on a phone: the landed Busy is on the first screen", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/home/hero-b2")
    await expect(page.locator('.hh-b2 .jc-landed [data-mode="busy"]')).toBeInViewport({ ratio: 1 })
    await expect(page.getByRole("link", { name: en.hero.primary }).first()).toBeInViewport()
    await context.close()
  })

  /** Where Busy's left edge sits against the event's: 0 when Busy covers the whole event. */
  const busyOffset = (page: Page) =>
    page.evaluate(() => {
      const slot = document.querySelector(".hh-c-slot")!.getBoundingClientRect()
      const busy = document.querySelector(".hh-c-cover")!.getBoundingClientRect()
      return Math.round(busy.x - slot.x)
    })

  test("/home/hero-c says its headline once to assistive technology, and rests on Busy without motion or JavaScript", async ({ browser }) => {
    for (const options of [{ reducedMotion: "reduce" as const }, { javaScriptEnabled: false }]) {
      const context = await browser.newContext(options)
      const page = await context.newPage()
      await page.goto("/home/hero-c")
      const heading = page.getByRole("heading", { level: 1 })
      await expect(heading).toHaveAccessibleName(en.variants.homeHeroes.c.title)
      await expect(heading.locator(".hh-c-says")).toHaveAttribute("aria-hidden", "true")
      await expect(heading.locator(".hh-c-busy")).toBeVisible()
      await expect(heading.locator(".hh-c-busy")).toContainText(en.demo.busy)
      expect(await busyOffset(page)).toBe(0)
      await page.waitForTimeout(2500)
      expect(await busyOffset(page)).toBe(0)
      await context.close()
    }
  })

  test("/home/hero-c lifts Busy off the Dentist within a few seconds, and its pause control stops it", async ({ page }) => {
    await page.goto("/home/hero-c")
    await expect.poll(() => busyOffset(page), { timeout: 3500 }).toBeLessThan(-20)
    await page.locator(".hh-c-stage").getByRole("button", { name: en.motion.pause }).click()
    await expect(page.locator(".hh-c-stage")).toHaveAttribute("data-playing", "false")
    // The compositor may draw one more frame after the pause lands.
    await page.waitForTimeout(150)
    const paused = await busyOffset(page)
    await page.waitForTimeout(800)
    expect(await busyOffset(page)).toBe(paused)
  })
})

test.describe("the versions index", () => {
  const listed = VERSIONS.flatMap((version) => version.iterations)

  test("every route it lists responds, and only production is in the sitemap", async ({ request }) => {
    const sitemap = await (await request.get("/sitemap-0.xml")).text()
    for (const { path } of listed) {
      expect((await request.get(path)).status(), path).toBe(200)
      if (path === "/") expect(sitemap).toContain("<loc>https://calendarghost.com/</loc>")
      else expect(sitemap, path).not.toContain(`calendarghost.com${path}<`)
    }
    expect((await request.get(VERSIONS_PATH)).status()).toBe(200)
    expect(sitemap).not.toContain(VERSIONS_PATH)
  })

  test("links every iteration, grouped by version, and is not indexed", async ({ page }) => {
    await page.goto(VERSIONS_PATH)
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex")
    for (const version of VERSIONS) {
      const group = page.getByRole("region", { name: version.name, exact: true })
      for (const iteration of version.iterations) {
        const link = group.getByRole("link", { name: iteration.name })
        await expect(link).toHaveAttribute("href", iteration.path)
        await expect(group).toContainText(iteration.commit)
        const entry = group.getByRole("listitem").filter({ has: page.getByRole("link", { name: iteration.name, exact: true }) })
        await expect(entry.locator(".versions-status")).toHaveText(STATUS_LABELS[iteration.status])
      }
    }
    for (const commit of ["20ec416", "92f5823", "579b106", "3b9dc7d"]) await expect(page.getByText(commit)).toBeVisible()
    await expect(page.getByText("git log -- site/")).toBeVisible()
  })

  test("every iteration that is not production links back to it from a fixed corner; production does not", async ({ page }) => {
    for (const path of NON_PRODUCTION_PATHS.filter((path) => path !== VERSIONS_PATH)) {
      await page.goto(path)
      const link = page.getByRole("link", { name: VERSIONS_LINK_LABEL, exact: true })
      await expect(link, path).toHaveAttribute("href", VERSIONS_PATH)
      expect(await link.evaluate((element) => getComputedStyle(element).position)).toBe("fixed")
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    await page.goto("/")
    await expect(page.getByRole("link", { name: VERSIONS_LINK_LABEL, exact: true })).toHaveCount(0)
  })
})
