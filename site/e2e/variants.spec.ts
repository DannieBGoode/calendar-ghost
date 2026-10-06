import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"
import { TRUST_DOCS } from "../src/links"
import {
  NON_PRODUCTION_PATHS,
  STATUS_LABELS,
  VERSIONS,
  VERSIONS_LINK_LABEL,
  VERSIONS_PATH,
  VIEW_WITH_GIT,
} from "../src/versions"

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
    path: "/home/hero-d",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero (its sequence plays once; its ghost blinks), the week, the home page's crossing. */
    loops: 3,
    controls: [".se-replay", ...HOME_CONTROLS],
  },
  {
    path: "/home/hero-e",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's travelling segments, the week, the home page's crossing. */
    loops: 3,
    controls: HOME_CONTROLS,
  },
  {
    path: "/home/hero-e2",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's run (it plays once, then its control replays it), the week, the home page's crossing. */
    loops: 3,
    controls: HOME_CONTROLS,
  },
  {
    path: "/home/hero-e3",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's run (it plays once; Replay sits beside Pause), the week, the home page's crossing. */
    loops: 3,
    controls: [".hb-view", ...HOME_CONTROLS],
  },
  {
    path: "/home/hero-e4",
    title: en.hero.title,
    rest: null,
    headings: HOME_HEADINGS,
    /** The hero's loop, the week, the home page's crossing. */
    loops: 3,
    controls: [".hc-view", ".hc-pause", ".hc-replay", ...HOME_CONTROLS],
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
      await expect(page.getByRole("button", { name: en.motion.pause, exact: true })).toHaveCount(0)
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
      await expect(page.getByRole("button", { name: en.motion.pause, exact: true })).toHaveCount(0)
      await context.close()
    })

    test("every loop has a pause control a finger can hit, and pausing stops it", async ({ page }) => {
      await page.goto(variant.path)
      await visitEverything(page)
      const buttons = page.getByRole("button", { name: en.motion.pause, exact: true })
      await expect(buttons).toHaveCount(variant.loops)
      for (const button of await buttons.all()) {
        expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      }
      // Each click turns a Pause button into Play, so the first Pause left is always the next one.
      for (let loop = 0; loop < variant.loops; loop += 1) {
        await buttons.first().scrollIntoViewIfNeeded()
        await buttons.first().click()
      }
      await expect(page.getByRole("button", { name: en.motion.play, exact: true })).toHaveCount(variant.loops)
      const endless = (await animations(page)).filter((animation) => animation.endTime === Infinity)
      expect(endless.length).toBeGreaterThan(0)
      for (const animation of endless.filter((animation) => animation.governed)) expect(animation.state, animation.name).toBe("paused")
      // Motion outside every demo stops by itself within five seconds of coming into view (WCAG
      // 2.2.2): there is no site-wide control, so no decorative loop runs on.
      for (const animation of await animations(page)) {
        if (animation.governed || animation.state !== "running") continue
        expect(animation.endTime, animation.name).toBeLessThanOrEqual(5000)
      }
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
    expect(preloads.some((href) => href?.includes("besley"))).toBe(false)
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
    path: "/home/hero-d",
    /** The two outputs side by side: every detail without Calendar Ghost, Busy with it. */
    point: ".se-split",
  },
  {
    path: "/home/hero-e",
    /** The whole diagram: every part, the ghost, and every calendar. */
    point: ".nd-wide",
    /** Its ghost is an outline drawn in Lantern Indigo, not the character (checked below). */
    character: false,
  },
  {
    path: "/home/hero-e2",
    /** The whole diagram: every calendar, the ghost, and Work's full column. */
    point: ".cn-wide",
    character: false,
  },
  {
    path: "/home/hero-e3",
    /** The whole diagram: Sam's calendars, the ghost, and the day with every event landed. */
    point: ".hb-wide",
  },
  {
    path: "/home/hero-e4",
    /** The diagram starts above the fold: its switch and the column labels under it. Hero E4 has
     * its own line and no meta line. */
    point: ".hc-views",
    line: en.variants.homeHeroes.hubE4.line,
    meta: false,
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
        const meta = !("meta" in hero && hero.meta === false)
        for (const selector of ["h1", ".hh-line", ".hh-ctas", ...(meta ? [".hh-meta"] : []), hero.point]) await fits(selector)
        await expect(page.locator(".hh-line")).toHaveText("line" in hero && hero.line ? hero.line : en.variants.homeHeroes.line)
        if (meta) await expect(page.locator(".hh-meta")).toHaveText(en.variants.homeHeroes.meta)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
        await context.close()
      })
    }

    if (hero.character === false) continue
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
})

test.describe("/home/hero-d", () => {
  const se = en.variants.homeHeroes.sameEvent
  const dentist = en.demo.events.dentist
  const details = [dentist.title, dentist.detail, en.crossing.guests, en.crossing.link, en.variants.journey.crossing.description]

  /** Whether every animation of the sequence has finished. */
  const rested = (page: Page) =>
    page
      .locator(".se")
      .evaluate((figure) =>
        figure
          .getAnimations({ subtree: true })
          .filter((animation) => (animation as CSSAnimation).animationName.startsWith("se-"))
          .every((animation) => animation.playState === "finished"),
      )

  /** The final state: work sees every detail without Calendar Ghost, and only Busy and the time with it. */
  async function expectFinalState(page: Page) {
    const exposed = page.locator(".se-without .se-exposed")
    for (const detail of details) await expect(exposed.getByText(detail, { exact: true })).toBeVisible()
    await expect(exposed.locator("li")).toHaveCount(5)
    for (const item of await exposed.locator("li").all()) await expect(item).toHaveCSS("opacity", "1")

    const busy = page.locator(".se-with .se-busy-event")
    await expect(busy.locator(".se-busy")).toHaveText(en.demo.busy)
    await expect(busy.locator(".se-busy")).toHaveCSS("opacity", "1")
    await expect(busy.locator('[data-fact="time"]')).toHaveCSS("opacity", "1")
    await expect(busy.locator('[data-fact="time"]')).toContainText("15:00–16:30")
    // Everything else on Work has faded and is hidden from assistive technology.
    const gone = busy.locator(".se-gone")
    await expect(gone).toHaveCount(5)
    for (const part of await gone.all()) {
      await expect(part).toHaveCSS("opacity", "0")
      await expect(part).toHaveAttribute("aria-hidden", "true")
    }
    expect(await busy.evaluate((element) => getComputedStyle(element, "::before").opacity)).toBe("0")
    // The rule's lines, in order, each ticked.
    await expect(page.locator(".se-with .se-cite")).toHaveText(se.rule.map((line) => `${line.key}: ${line.value}`))
    for (const tick of await page.locator(".se-with .se-tick .se-icon").all()) await expect(tick).toHaveCSS("opacity", "1")
    await expect(page.locator(".se-without .se-cite")).toHaveText(se.shared.map((line) => `${line.key}: ${line.value}`))
  }

  test("plays once: the rule ticks in, Busy is left on the with side, every detail stays on the without side", async ({ page }) => {
    await page.goto("/home/hero-d")
    // Partway through, the with side still shows the Dentist's title.
    await page.waitForTimeout(800)
    expect(Number(await page.locator(".se-with .se-busy").evaluate((element) => getComputedStyle(element).opacity))).toBeLessThan(1)
    await expect.poll(() => rested(page), { timeout: 6000 }).toBe(true)
    await expectFinalState(page)
  })

  test("without JavaScript or with reduced motion, it shows the final state at once", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext(options)
      const page = await context.newPage()
      await page.goto("/home/hero-d")
      await expectFinalState(page)
      await expect(page.locator(".se-replay")).toBeHidden()
      await context.close()
    }
  })

  test("Replay runs the sequence again; Pause holds it", async ({ page }) => {
    await page.goto("/home/hero-d")
    await expect.poll(() => rested(page), { timeout: 6000 }).toBe(true)
    const busyOpacity = () => page.locator(".se-with .se-busy").evaluate((element) => Number(getComputedStyle(element).opacity))
    await page.getByRole("button", { name: se.replay }).click()
    expect(await rested(page)).toBe(false)
    expect(await busyOpacity()).toBeLessThan(1)
    await page.locator(".se").getByRole("button", { name: en.motion.pause }).click()
    await expect(page.locator(".se")).toHaveAttribute("data-playing", "false")
    const held = await busyOpacity()
    await page.waitForTimeout(4500)
    expect(await busyOpacity()).toBe(held)
    expect(await rested(page)).toBe(false)
    await page.locator(".se").getByRole("button", { name: en.motion.play }).click()
    await expect.poll(() => rested(page), { timeout: 6000 }).toBe(true)
    await expectFinalState(page)
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: a small ghost, ${scheme === "light" ? "outlined, with no halo" : "white and glowing"}`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-d")
      const ghost = page.locator(".se-ghost .ghost")
      await expect(ghost).toHaveAttribute("data-tone", "mist")
      expect((await ghost.boundingBox())!.width).toBeLessThanOrEqual(32)
      const glow = await ghost.evaluate((element) => getComputedStyle(element, "::before").backgroundColor)
      if (scheme === "light") expect(glow).toBe("rgba(0, 0, 0, 0)")
      else expect(glow).not.toBe("rgba(0, 0, 0, 0)")
      // The ghost rests beside the last line it applied.
      const last = (await page.locator(".se-with .se-cite").last().boundingBox())!
      const box = (await ghost.boundingBox())!
      expect(Math.abs(box.y + box.height / 2 - (last.y + last.height / 2))).toBeLessThan(3)
      await context.close()
    })
  }

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the two outputs stay side by side, inside the page`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-d")
      const without = (await page.locator(".se-exposed").boundingBox())!
      const busy = (await page.locator(".se-busy-event").boundingBox())!
      expect(Math.abs(without.y - busy.y)).toBeLessThan(1)
      expect(Math.abs(without.height - busy.height)).toBeLessThan(1)
      expect(busy.x).toBeGreaterThan(without.x + without.width)
      expect(busy.x + busy.width).toBeLessThanOrEqual(width)
      // Every rule line keeps to its own row: none overlaps the next.
      const lines = await page.locator(".se-with .se-cite-text").evaluateAll((all) => all.map((line) => line.getBoundingClientRect().bottom))
      const tops = await page.locator(".se-with .se-cite").evaluateAll((all) => all.map((line) => line.getBoundingClientRect().top))
      for (let index = 1; index < tops.length; index += 1) expect(lines[index - 1]).toBeLessThanOrEqual(tops[index] + 0.5)
      await context.close()
    })
  }
})

test.describe("/home/hero-e", () => {
  const nd = en.variants.homeHeroes.nodeDiagram
  const NEVER = ["guests", "organizer", "link", "attachments", "invitations"]
  const DETAILS = ["title", "place", "description"]
  const CALENDARS = ["work", "family", "personal"]

  /** A segment's dash offset, in diagram units: on its path when negative or zero. */
  const offset = (page: Page, selector: string) =>
    page.locator(selector).evaluate((element) => Number.parseFloat(getComputedStyle(element).strokeDashoffset))

  /** The diagram's own animations (not the rest of the page's). */
  const loop = (page: Page) =>
    page.locator(".nd").evaluate((figure) => figure.getAnimations({ subtree: true }).map((animation) => animation.playState))

  test("without JavaScript or with reduced motion, the still diagram shows every route and every stop", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options })
      const page = await context.newPage()
      await page.goto("/home/hero-e")
      await expect(page.locator(".nd-wide")).toBeVisible()
      await expect(page.locator(".nd-tall")).toBeHidden()
      expect(await loop(page)).toEqual([])
      const wide = ".nd-wide"
      // The time runs into the ghost and out to every calendar.
      expect(await offset(page, `${wide} .nd-leg[data-part="time"]:not([data-to])`)).toBeLessThan(0)
      for (const calendar of CALENDARS) expect(await offset(page, `${wide} .nd-leg[data-part="time"][data-to="${calendar}"]`), calendar).toBeLessThan(0)
      // The details run into the ghost and out only to Personal.
      for (const part of DETAILS) {
        expect(await offset(page, `${wide} .nd-leg[data-part="${part}"]:not([data-to])`), part).toBeLessThan(0)
        await expect(page.locator(`${wide} .nd-leg[data-part="${part}"][data-to]`)).toHaveAttribute("data-to", "personal")
      }
      // The parts that never cross over show their stop and cap, and go nowhere.
      for (const part of NEVER) {
        const stop = page.locator(`${wide} .nd-stop[data-part="${part}"]`)
        await expect(stop).toBeVisible()
        await expect(stop).toHaveCSS("opacity", "1")
        // The cap is a short line across the curve (no width, so measured by its height).
        expect((await stop.locator(".nd-cap").boundingBox())!.height, part).toBeGreaterThan(6)
        await expect(page.locator(`${wide} .nd-leg[data-part="${part}"][data-to]`)).toHaveCount(0)
      }
      await expect(page.locator(`${wide} .nd-stop`)).toHaveCount(NEVER.length)
      await context.close()
    }
  })

  test("its segments travel, its stops come and go, and the pause control holds them", async ({ page }) => {
    await page.goto("/home/hero-e")
    const time = '.nd-wide .nd-leg[data-part="time"]:not([data-to])'
    // The time sets off first, within a second.
    await expect.poll(() => offset(page, time), { timeout: 2000 }).toBeLessThan(0)
    const before = await offset(page, time)
    await page.waitForTimeout(300)
    expect(await offset(page, time)).toBeLessThan(before)
    // A stop is out of sight until its segment reaches it.
    await expect(page.locator('.nd-wide .nd-stop[data-part="invitations"]')).toHaveCSS("opacity", "0")

    await page.locator(".nd").getByRole("button", { name: en.motion.pause }).click()
    await expect(page.locator(".nd")).toHaveAttribute("data-playing", "false")
    await expect.poll(async () => new Set(await loop(page))).toEqual(new Set(["paused"]))
    // A pause takes hold on the next frame.
    await page.waitForTimeout(200)
    const held = await offset(page, time)
    await page.waitForTimeout(500)
    expect(await offset(page, time)).toBe(held)
    await page.locator(".nd").getByRole("button", { name: en.motion.play }).click()
    await expect(page.locator(".nd")).toHaveAttribute("data-playing", "true")
    await expect.poll(async () => new Set(await loop(page))).toEqual(new Set(["running"]))
  })

  test("off screen, the loop holds", async ({ page }) => {
    await page.goto("/home/hero-e")
    await expect.poll(() => loop(page)).toContain("running")
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.locator(".nd")).toHaveAttribute("data-offscreen", "")
    await expect.poll(async () => new Set(await loop(page))).toEqual(new Set(["paused"]))
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page.locator(".nd")).not.toHaveAttribute("data-offscreen", "")
    await expect.poll(async () => new Set(await loop(page))).toEqual(new Set(["running"]))
  })

  test("tells screen readers the same facts, and hides the drawing from them", async ({ page }) => {
    await page.goto("/home/hero-e")
    await expect(page.getByRole("figure", { name: nd.summary })).toBeAttached()
    await expect(page.locator(".nd li")).toHaveText(nd.facts)
    for (const svg of await page.locator(".nd svg").all()) await expect(svg).toHaveAttribute("aria-hidden", "true")
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: hairlines and outlines only, the ghost in Lantern Indigo`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e")
      const primary = await page.locator(".hh-accent").evaluate((element) => getComputedStyle(element).color)
      await expect(page.locator(".nd-wide .nd-ghost")).toHaveCSS("stroke", primary)
      const decorated = await page.locator(".nd").evaluate((figure) =>
        [figure, ...figure.querySelectorAll("*")].filter((element) => {
          const style = getComputedStyle(element)
          return style.boxShadow !== "none" || style.filter !== "none" || style.backgroundImage !== "none"
        }).length,
      )
      expect(decorated).toBe(0)
      await context.close()
    })
  }

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the diagram turns: the parts on top, the ghost in the middle, the calendars below`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e")
      await expect(page.locator(".nd-wide")).toBeHidden()
      const tall = page.locator(".nd-tall")
      await expect(tall).toBeVisible()
      const box = (await tall.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      const boxes = async (selector: string) => Promise.all((await tall.locator(selector).all()).map(async (item) => (await item.boundingBox())!))
      const parts = await boxes(".nd-pill:not(.nd-destination)")
      const calendars = await boxes(".nd-destination")
      const ghost = (await tall.locator(".nd-ghost").boundingBox())!
      expect(parts).toHaveLength(9)
      expect(Math.max(...parts.map((part) => part.y + part.height))).toBeLessThan(ghost.y)
      expect(ghost.y + ghost.height).toBeLessThan(Math.min(...calendars.map((calendar) => calendar.y)))
      // Three calendars side by side, every stop and the time's route still drawn.
      expect(new Set(calendars.map((calendar) => Math.round(calendar.y))).size).toBe(1)
      for (const calendar of CALENDARS) expect(await offset(page, `.nd-tall .nd-leg[data-part="time"][data-to="${calendar}"]`)).toBeLessThan(0)
      for (const part of NEVER) await expect(tall.locator(`.nd-stop[data-part="${part}"]`)).toBeVisible()
      await context.close()
    })
  }
})

test.describe("/home/hero-e2", () => {
  const cn = en.variants.homeHeroes.consolidation
  const SOURCES = ["personal", "family", "kidsSchool", "runningClub", "sideProject"]

  /** The diagram's own animations' states (not the rest of the page's). */
  const run = (page: Page) =>
    page.locator(".cn").evaluate((figure) => figure.getAnimations({ subtree: true }).map((animation) => animation.playState))
  const opacity = (page: Page, selector: string) =>
    page.locator(selector).evaluate((element) => Number(getComputedStyle(element).opacity))

  /** The final state: every calendar has one Busy block on Work, beside Work's own Standup. */
  async function expectFullColumn(page: Page, layout: "wide" | "tall") {
    const pills = page.locator(`.cn-${layout} .cn-pill`)
    await expect(pills).toHaveCount(SOURCES.length)
    const busy = page.locator(`.cn-${layout} .cn-busy`)
    await expect(busy).toHaveCount(await pills.count())
    for (const source of SOURCES) {
      const block = page.locator(`.cn-${layout} .cn-busy[data-source="${source}"]`)
      await expect(block, source).toBeVisible()
      await expect(block, source).toHaveCSS("opacity", "1")
      await expect(block.locator(".cn-slot-title"), source).toHaveText(en.demo.busy)
    }
    await expect(page.locator(`.cn-${layout} .cn-meeting .cn-slot-title`)).toHaveText(en.demo.events.standup.title)
    // Nothing but Busy reaches Work: no event of Sam's own calendars is named there.
    const work = page.locator(`.cn-${layout} .cn-work`)
    for (const title of [en.demo.events.dentist.title, ...Object.values(cn.events)]) await expect(work).not.toContainText(title)
  }

  test("without JavaScript or with reduced motion, the Work column shows one Busy block per calendar, and nothing travels", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options })
      const page = await context.newPage()
      await page.goto("/home/hero-e2")
      await expect(page.locator(".cn-wide")).toBeVisible()
      await expect(page.locator(".cn-tall")).toBeHidden()
      expect(await run(page)).toEqual([])
      await expectFullColumn(page, "wide")
      // Every hairline is drawn; every segment rests out of sight, before its path.
      await expect(page.locator(".cn-wide .cn-curves path")).toHaveCount(SOURCES.length * 2)
      for (const leg of await page.locator(".cn-wide .cn-leg").all()) {
        expect(await leg.evaluate((element) => Number.parseFloat(getComputedStyle(element).strokeDashoffset))).toBeGreaterThan(0)
      }
      await expect(page.locator(".cn button")).toBeHidden()
      await context.close()
    }
  })

  test("plays once: the Busy blocks land one by one, the column rests full, and the control turns into Replay", async ({ page }) => {
    await page.goto("/home/hero-e2")
    // At first only some have landed; the Dentist's shows within three seconds.
    expect(await opacity(page, '.cn-wide .cn-busy[data-source="sideProject"]')).toBeLessThan(1)
    await expect.poll(() => opacity(page, '.cn-wide .cn-busy[data-source="personal"]'), { timeout: 3000 }).toBeGreaterThan(0.5)
    await expect(page.locator(".cn").getByRole("button", { name: cn.replay })).toBeVisible({ timeout: 12_000 })
    expect(new Set(await run(page))).toEqual(new Set(["finished"]))
    await expectFullColumn(page, "wide")
    // Replay starts it over: the column empties of Busy and fills again.
    await page.locator(".cn").getByRole("button", { name: cn.replay }).click()
    expect(await opacity(page, '.cn-wide .cn-busy[data-source="sideProject"]')).toBe(0)
    await expect(page.locator(".cn").getByRole("button", { name: en.motion.pause })).toBeVisible()
    await expect(page.locator(".cn").getByRole("button", { name: cn.replay })).toBeVisible({ timeout: 12_000 })
    await expectFullColumn(page, "wide")
  })

  test("the pause control holds the run where it is, and Play lets it go on", async ({ page }) => {
    await page.goto("/home/hero-e2")
    await page.locator(".cn").getByRole("button", { name: en.motion.pause }).click()
    await expect(page.locator(".cn")).toHaveAttribute("data-playing", "false")
    await expect.poll(async () => (await run(page)).includes("running")).toBe(false)
    const held = await opacity(page, '.cn-wide .cn-busy[data-source="sideProject"]')
    expect(held).toBe(0)
    await page.waitForTimeout(8000)
    expect(await opacity(page, '.cn-wide .cn-busy[data-source="sideProject"]')).toBe(held)
    await page.locator(".cn").getByRole("button", { name: en.motion.play }).click()
    await expect(page.locator(".cn")).toHaveAttribute("data-playing", "true")
    await expect(page.locator(".cn").getByRole("button", { name: cn.replay })).toBeVisible({ timeout: 12_000 })
    await expectFullColumn(page, "wide")
  })

  test("off screen, the run holds", async ({ page }) => {
    await page.goto("/home/hero-e2")
    await expect.poll(() => run(page)).toContain("running")
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.locator(".cn")).toHaveAttribute("data-offscreen", "")
    await expect.poll(async () => (await run(page)).includes("running")).toBe(false)
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page.locator(".cn")).not.toHaveAttribute("data-offscreen", "")
    await expect.poll(() => run(page)).toContain("running")
  })

  test("tells screen readers what it shows, and hides the drawing from them", async ({ page }) => {
    await page.goto("/home/hero-e2")
    const figure = page.getByRole("figure", { name: cn.summary })
    await expect(figure).toBeAttached()
    await expect(figure.locator("p.sr-only")).toHaveText(cn.fact)
    for (const svg of await page.locator(".cn svg").all()) await expect(svg).toHaveAttribute("aria-hidden", "true")
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: hairlines and outlines only, the ghost and every Busy in Lantern Indigo`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e2")
      const primary = await page.locator(".hh-accent").evaluate((element) => getComputedStyle(element).color)
      await expect(page.locator(".cn-wide .cn-ghost")).toHaveCSS("stroke", primary)
      for (const title of await page.locator(".cn-wide .cn-busy .cn-slot-title").all()) await expect(title).toHaveCSS("fill", primary)
      const decorated = await page.locator(".cn").evaluate((figure) =>
        [figure, ...figure.querySelectorAll("*")].filter((element) => {
          const style = getComputedStyle(element)
          return style.boxShadow !== "none" || style.filter !== "none" || style.backgroundImage !== "none"
        }).length,
      )
      expect(decorated).toBe(0)
      await context.close()
    })
  }

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the diagram runs down: the calendars in two columns, the ghost, then Work's full column`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e2")
      await expect(page.locator(".cn-wide")).toBeHidden()
      const tall = page.locator(".cn-tall")
      await expect(tall).toBeVisible()
      const box = (await tall.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      const pills = await Promise.all((await tall.locator(".cn-pill").all()).map(async (item) => (await item.boundingBox())!))
      const ghost = (await tall.locator(".cn-ghost").boundingBox())!
      const work = (await tall.locator(".cn-work-box").boundingBox())!
      expect(new Set(pills.map((pill) => Math.round(pill.x))).size).toBe(2)
      expect(Math.max(...pills.map((pill) => pill.y + pill.height))).toBeLessThan(ghost.y)
      expect(ghost.y + ghost.height).toBeLessThan(work.y)
      await expectFullColumn(page, "tall")
      await context.close()
    })
  }
})

test.describe("/home/hero-e3", () => {
  const hb = en.variants.homeHeroes.hub
  const dentist = en.demo.events.dentist.title
  const standup = en.demo.events.standup.title
  const dinner = hb.events.familyDinner

  /** The diagram's own animations' states (not the rest of the page's). */
  const run = (page: Page) =>
    page.locator(".hb").evaluate((figure) => figure.getAnimations({ subtree: true }).map((animation) => animation.playState))
  const opacity = (page: Page, selector: string) => page.locator(selector).first().evaluate((element) => Number(getComputedStyle(element).opacity))
  const block = (layout: "wide" | "tall", source: string) => `.hb-${layout} .hb-block[data-source="${source}"]`

  /** The final state, as work sees it: Work's own Standup with its title, the Dentist and the
   * family dinner as Busy at their times, and their titles kept by the ghost, struck through. */
  async function expectWorkSees(page: Page, layout: "wide" | "tall") {
    await expect(page.locator(`.hb-${layout} .hb-block`)).toHaveCount(3)
    for (const item of await page.locator(`.hb-${layout} .hb-block`).all()) await expect(item).toHaveCSS("opacity", "1")
    await expect(page.locator(`${block(layout, "work")} text`)).toHaveText(new RegExp(`^${standup}\\s*10:00–11:00$`))
    await expect(page.locator(`${block(layout, "personal")} .hb-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*15:00–16:30$`))
    await expect(page.locator(`${block(layout, "family")} .hb-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*18:30–19:30$`))
    for (const source of ["personal", "family"]) {
      expect(await opacity(page, `${block(layout, source)} .hb-as-work`), source).toBe(1)
      expect(await opacity(page, `${block(layout, source)} .hb-as-you`), source).toBe(0)
    }
    expect(await opacity(page, `.hb-${layout} .hb-work .hb-head.hb-as-work`)).toBe(1)
    await expect(page.locator(`.hb-${layout} .hb-work .hb-head.hb-as-work`)).toContainText(en.app.rules.accounts.work)
    await expect(page.locator(`.hb-${layout} .hb-trace`)).toHaveText([dentist, dinner])
    for (const trace of await page.locator(`.hb-${layout} .hb-trace`).all()) {
      await expect(trace).toHaveCSS("opacity", "1")
      await expect(trace).toHaveCSS("text-decoration-line", "line-through")
    }
    expect(await opacity(page, `.hb-${layout} .hb-traces`)).toBe(1)
  }

  test("without JavaScript or with reduced motion: what work sees, with the Dentist as Busy 15:00–16:30 and the Standup with its title; nothing travels", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options })
      const page = await context.newPage()
      await page.goto("/home/hero-e3")
      await expect(page.locator(".hb-wide")).toBeVisible()
      await expect(page.locator(".hb-tall")).toBeHidden()
      expect(await run(page)).toEqual([])
      await expect(page.locator(".hb-wide .hb-pill")).toHaveText([
        new RegExp(`${en.demo.calendars.work}\\s*${standup} 10:00`),
        new RegExp(`${en.demo.calendars.personal}\\s*${dentist} 15:00`),
        new RegExp(`${en.demo.calendars.family}\\s*${dinner} 18:30`),
      ])
      await expectWorkSees(page, "wide")
      await expect(page.locator(".hb-wide .hb-curves path")).toHaveCount(6)
      for (const chip of await page.locator(".hb-wide .hb-chip").all()) await expect(chip).toHaveCSS("opacity", "0")
      expect(await opacity(page, ".hb-wide .hb-ghost .ghost-face-then")).toBe(1)
      if (options.javaScriptEnabled === false) {
        // The drawing's own label stands in for the switch.
        await expect(page.locator(".hb-wide .hb-label-work")).toHaveText(en.demo.workSees)
        await expect(page.locator(".hb-controls")).toBeHidden()
      } else {
        await expect(page.getByRole("button", { name: en.motion.pause, exact: true })).toHaveCount(0)
        await expect(page.locator(".hb").getByRole("button", { name: hb.replay })).toBeHidden()
      }
      await context.close()
    }
  })

  test("plays once, left to right: every chip goes through the ghost; the Dentist's title drops there and it comes out Busy, the Standup keeps its own; then it rests", async ({ page }) => {
    await page.goto("/home/hero-e3")
    expect(await opacity(page, block("wide", "family"))).toBeLessThan(1)
    const into = page.locator('.hb-wide .hb-chip[data-source="personal"][data-side="in"]')
    await expect(into).toHaveText(dentist)
    await expect(into).toHaveAttribute("data-drops", "")
    await expect(page.locator('.hb-wide .hb-chip[data-source="personal"][data-side="out"] .hb-as-work')).toHaveText(en.demo.busy)
    await expect(page.locator('.hb-wide .hb-chip[data-source="work"][data-side="in"]')).not.toHaveAttribute("data-drops", "")
    await expect(page.locator('.hb-wide .hb-chip[data-source="work"][data-side="out"]')).toHaveText(standup)
    await expect.poll(() => opacity(page, '.hb-wide .hb-chip[data-source="personal"][data-side="out"]'), { timeout: 4000 }).toBeGreaterThan(0.5)
    await expect.poll(() => opacity(page, block("wide", "personal")), { timeout: 4000 }).toBeGreaterThan(0.5)
    await expect(page.locator(".hb").getByRole("button", { name: en.motion.pause })).toBeDisabled({ timeout: 14_000 })
    expect(new Set(await run(page))).toEqual(new Set(["finished"]))
    await expectWorkSees(page, "wide")
    // Replay, beside Pause, starts it over: the blocks go, and land again.
    await page.locator(".hb").getByRole("button", { name: hb.replay }).click()
    expect(await opacity(page, block("wide", "family"))).toBe(0)
    await expect(page.locator(".hb").getByRole("button", { name: en.motion.pause })).toBeEnabled()
    await expect(page.locator(".hb").getByRole("button", { name: en.motion.pause })).toBeDisabled({ timeout: 14_000 })
    await expectWorkSees(page, "wide")
  })

  test("the ghost is pleased as a chip passes, and neutral between chips", async ({ page }) => {
    await page.goto("/home/hero-e3")
    const seen = await page.locator(".hb-wide .hb-ghost .ghost-face-then").evaluate(
      (face) =>
        new Promise<number[]>((resolve) => {
          const samples: number[] = []
          const timer = setInterval(() => samples.push(Math.round(Number(getComputedStyle(face).opacity))), 40)
          setTimeout(() => {
            clearInterval(timer)
            resolve(samples)
          }, 3500)
        }),
    )
    const changes = seen.filter((value, index) => index === 0 || value !== seen[index - 1])
    expect(changes.slice(0, 4)).toEqual([0, 1, 0, 1])
  })

  test("the pause control holds the run where it is, and Play lets it go on", async ({ page }) => {
    await page.goto("/home/hero-e3")
    await page.locator(".hb").getByRole("button", { name: en.motion.pause }).click()
    await expect(page.locator(".hb")).toHaveAttribute("data-playing", "false")
    await expect.poll(async () => (await run(page)).includes("running")).toBe(false)
    expect(await opacity(page, block("wide", "family"))).toBe(0)
    await page.waitForTimeout(8000)
    expect(await opacity(page, block("wide", "family"))).toBe(0)
    await page.locator(".hb").getByRole("button", { name: en.motion.play }).click()
    await expect(page.locator(".hb")).toHaveAttribute("data-playing", "true")
    await expect(page.locator(".hb").getByRole("button", { name: en.motion.pause })).toBeDisabled({ timeout: 14_000 })
    await expectWorkSees(page, "wide")
  })

  test("off screen, the run holds", async ({ page }) => {
    await page.goto("/home/hero-e3")
    await expect.poll(() => run(page)).toContain("running")
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.locator(".hb")).toHaveAttribute("data-offscreen", "")
    await expect.poll(async () => (await run(page)).includes("running")).toBe(false)
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect(page.locator(".hb")).not.toHaveAttribute("data-offscreen", "")
    await expect.poll(() => run(page)).toContain("running")
  })

  test("the switch turns the day on the right into Sam's Personal calendar, every title kept, and back", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/home/hero-e3")
    const views = page.getByRole("group", { name: hb.viewLabel })
    const work = views.getByRole("button", { name: en.demo.workSees })
    const you = views.getByRole("button", { name: en.demo.youSee })
    await expect(work).toHaveAttribute("aria-pressed", "true")
    await expect(you).toHaveAttribute("aria-pressed", "false")
    for (const button of [work, you]) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    // The drawing's own label gives way to the switch.
    await expect(page.locator(".hb-wide .hb-label-work")).toBeHidden()
    await expectWorkSees(page, "wide")

    // Under reduced motion it switches at once.
    await you.click()
    await expect(you).toHaveAttribute("aria-pressed", "true")
    await expect(page.locator(".hb")).toHaveAttribute("data-view", "you")
    expect(await opacity(page, ".hb-wide .hb-work .hb-head.hb-as-you")).toBe(1)
    expect(await opacity(page, ".hb-wide .hb-work .hb-head.hb-as-work")).toBe(0)
    await expect(page.locator(".hb-wide .hb-work .hb-head.hb-as-you")).toContainText(en.demo.calendars.personal)
    await expect(page.locator(".hb-wide .hb-work .hb-head.hb-as-you")).toContainText(en.app.rules.accounts.personal)
    await expect(page.locator(`${block("wide", "personal")} .hb-as-you`)).toHaveText(new RegExp(`^${dentist}\\s*15:00–16:30$`))
    await expect(page.locator(`${block("wide", "family")} .hb-as-you`)).toHaveText(new RegExp(`^${dinner}\\s*18:30–19:30$`))
    for (const source of ["personal", "family"]) {
      expect(await opacity(page, `${block("wide", source)} .hb-as-you`), source).toBe(1)
      expect(await opacity(page, `${block("wide", source)} .hb-as-work`), source).toBe(0)
    }
    await expect(page.locator(`${block("wide", "work")} text`)).toHaveText(new RegExp(`^${standup}`))
    // Nothing is held back on the way to Personal, so no title rests by the ghost.
    expect(await opacity(page, ".hb-wide .hb-traces")).toBe(0)

    await work.click()
    await expect(page.locator(".hb")).toHaveAttribute("data-view", "work")
    await expectWorkSees(page, "wide")
    await context.close()
  })

  test("tells screen readers what work sees of each event, and what Sam sees instead, and hides the drawing from them", async ({ page }) => {
    await page.goto("/home/hero-e3")
    const figure = page.getByRole("figure", { name: hb.summary })
    await expect(figure).toBeAttached()
    await expect(figure.locator("ul.sr-only li")).toHaveText([
      "Standup, Work's own meeting, shows with its title, from 10:00 to 11:00.",
      "Dentist from Personal appears on Work as Busy, from 15:00 to 16:30.",
      "Family dinner from Family appears on Work as Busy, from 18:30 to 19:30.",
      hb.never,
      hb.youFact,
    ])
    for (const svg of await page.locator(".hb .hb-svg").all()) await expect(svg).toHaveAttribute("aria-hidden", "true")
    for (const ghost of await page.locator(".hb .ghost").all()) await expect(ghost).toHaveAttribute("aria-hidden", "true")
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: hairlines and outlines only, Busy in Lantern Indigo with its calendar's dot, and the white ghost 88 to 104px wide, ${scheme === "light" ? "with no halo" : "glowing"}`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e3")
      const primary = await page.locator(".hh-accent").evaluate((element) => getComputedStyle(element).color)
      for (const title of await page.locator('.hb-wide .hb-block[data-shows="busy"] .hb-as-work .hb-block-title').all()) await expect(title).toHaveCSS("fill", primary)
      for (const source of ["personal", "family"]) {
        const ring = await page.locator(`.hb-wide .hb-pill[data-calendar="${source}"] .hb-ring`).evaluate((element) => getComputedStyle(element).stroke)
        await expect(page.locator(`${block("wide", source)} .hb-source-dot`)).toHaveCSS("fill", ring)
      }
      const ghost = page.locator(".hb-wide .hb-ghost .ghost")
      await expect(ghost).toHaveAttribute("data-tone", "mist")
      const box = (await ghost.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(88)
      expect(box.width).toBeLessThanOrEqual(104)
      const glow = await ghost.evaluate((element) => getComputedStyle(element, "::before").backgroundColor)
      if (scheme === "light") expect(glow).toBe("rgba(0, 0, 0, 0)")
      else expect(glow).not.toBe("rgba(0, 0, 0, 0)")
      const decorated = await page.locator(".hb").evaluate((figure) =>
        [figure, ...figure.querySelectorAll("*")].filter((element) => {
          const style = getComputedStyle(element)
          return style.boxShadow !== "none" || style.filter !== "none" || style.backgroundImage !== "none"
        }).length,
      )
      expect(decorated).toBe(0)
      await context.close()
    })
  }

  test("keeps the headline, the line, the calls to action, and the facts together in one block above the diagram", async ({ page }) => {
    await page.goto("/home/hero-e3")
    const boxes = await Promise.all(["h1", ".hh-line", ".hh-ctas", ".hh-meta", ".hb"].map(async (selector) => (await page.locator(selector).first().boundingBox())!))
    const [title, line, ctas, meta, figure] = boxes as [DOMRect, DOMRect, DOMRect, DOMRect, DOMRect]
    for (const box of [line, ctas]) expect(Math.abs(box.x - title.x)).toBeLessThan(2)
    expect(line.y).toBeGreaterThan(title.y + title.height - 1)
    expect(ctas.y).toBeGreaterThan(line.y + line.height - 1)
    expect(meta.y + meta.height).toBeLessThan(figure.y)
    // Besley at its natural spacing: never tightened (the display face changed after this hero).
    expect(parseFloat(await page.locator("h1").evaluate((element) => getComputedStyle(element).letterSpacing))).toBeGreaterThanOrEqual(0)
  })

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the diagram runs down: the calendars in two columns, the ghost, then the day, all inside the page`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e3")
      await expect(page.locator(".hb-wide")).toBeHidden()
      const tall = page.locator(".hb-tall")
      await expect(tall).toBeVisible()
      const box = (await tall.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      const pills = await Promise.all((await tall.locator(".hb-pill").all()).map(async (item) => (await item.boundingBox())!))
      const ghost = (await tall.locator(".hb-ghost").boundingBox())!
      const work = (await tall.locator(".hb-work .hb-box").boundingBox())!
      const views = (await page.getByRole("group", { name: hb.viewLabel }).boundingBox())!
      expect(new Set(pills.map((pill) => Math.round(pill.x))).size).toBe(2)
      expect(Math.max(...pills.map((pill) => pill.y + pill.height))).toBeLessThan(ghost.y)
      expect(ghost.y + ghost.height).toBeLessThan(work.y)
      expect(views.y + views.height).toBeLessThanOrEqual(work.y + 2)
      expect(views.x + views.width).toBeLessThanOrEqual(width)
      await expectWorkSees(page, "tall")
      await context.close()
    })
  }
})

test.describe("/home/hero-e4", () => {
  const hc = en.variants.homeHeroes.hubE4
  const gym = en.demo.events.gym.title
  const call = en.demo.events.clientCall.title
  const dinner = hc.events.familyDinner

  /** The diagram's own animations (not the rest of the page's). */
  const run = (page: Page) =>
    page.locator(".hc").evaluate((figure) =>
      figure.getAnimations({ subtree: true }).map((animation) => ({
        name: (animation as CSSAnimation).animationName,
        state: animation.playState,
        iterations: animation.effect?.getComputedTiming().iterations,
      })),
    )
  const opacity = (page: Page, selector: string) => page.locator(selector).first().evaluate((element) => Number(getComputedStyle(element).opacity))
  const block = (layout: "wide" | "tall", source: string) => `.hc-${layout} .hc-block[data-source="${source}"]`
  /** Any CSS colour (oklch included) as sRGB channels, read back from a one-pixel canvas. */
  const rgb = (page: Page, color: string) =>
    page.evaluate((value) => {
      const context = document.createElement("canvas").getContext("2d")!
      context.fillStyle = value
      context.fillRect(0, 0, 1, 1)
      return [...context.getImageData(0, 0, 1, 1).data.slice(0, 3)] as [number, number, number]
    }, color)

  /** The rest state, as work sees it: Work's own client call with its title, the gym session and
   * the family dinner as Busy at their times, and their titles kept back by the ghost. */
  async function expectWorkSees(page: Page, layout: "wide" | "tall") {
    for (const item of await page.locator(`.hc-${layout} .hc-block`).all()) await expect(item).toHaveCSS("opacity", "1")
    await expect(page.locator(`${block(layout, "work")} text`)).toHaveText(new RegExp(`^${call}\\s*14:30–15:30$`))
    await expect(page.locator(`${block(layout, "personal")} .hc-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*12:00–13:00$`))
    await expect(page.locator(`${block(layout, "family")} .hc-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*18:00–19:00$`))
    expect(await opacity(page, `.hc-${layout} .hc-head.hc-as-work`)).toBe(1)
    await expect(page.locator(`.hc-${layout} .hc-kept-caption`)).toHaveText(hc.kept)
    await expect(page.locator(`.hc-${layout} .hc-kept-title`)).toHaveText([gym, dinner])
    expect(await opacity(page, `.hc-${layout} .hc-kept`)).toBe(1)
    for (const title of await page.locator(`.hc-${layout} .hc-kept-title`).all()) await expect(title).toHaveCSS("opacity", "1")
  }

  test("without JavaScript or with reduced motion: everything has landed, as work sees it, and nothing moves", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options })
      const page = await context.newPage()
      await page.goto("/home/hero-e4")
      expect((await run(page)).filter((animation) => animation.state === "running")).toEqual([])
      await expect(page.locator(".hc-wide .hc-pill")).toHaveText([
        new RegExp(`${en.demo.calendars.personal}\\s*${gym} 12:00`),
        new RegExp(`${en.demo.calendars.work}\\s*${call} 14:30`),
        new RegExp(`${en.demo.calendars.family}\\s*${dinner} 18:00`),
      ])
      await expect(page.locator(".hc-wide .hc-label").first()).toHaveText(hc.calendarsLabel)
      await expect(page.locator(".hc-wide .hc-label.hc-as-work")).toHaveText(hc.dayLabels.work)
      await expectWorkSees(page, "wide")
      for (const chip of await page.locator(".hc-wide .hc-chip").all()) await expect(chip).toHaveCSS("opacity", "0")
      if (options.javaScriptEnabled === false) {
        await expect(page.locator(".hc-static-view")).toHaveText(en.demo.workSees)
        await expect(page.locator(".hc-controls")).toBeHidden()
      } else {
        await expect(page.locator(".hc-static-view")).toBeHidden()
        await expect(page.locator(".hc").getByRole("button", { name: en.motion.pause })).toHaveCount(0)
      }
      await context.close()
    }
  })

  test("keeps the hero to the headline, its one line, and the calls to action", async ({ page }) => {
    await page.goto("/home/hero-e4")
    await expect(page.locator(".hh-line")).toHaveText(hc.line)
    await expect(page.locator(".hh-meta")).toHaveCount(0)
  })

  test("loops calmly, with a small labelled Pause and Replay in the diagram's bottom-right corner", async ({ page }) => {
    await page.goto("/home/hero-e4")
    const animations = await run(page)
    expect(animations.length).toBeGreaterThan(10)
    for (const animation of animations) expect(animation.iterations, animation.name).toBe(Infinity)
    const pause = page.locator(".hc").getByRole("button", { name: en.motion.pause })
    const replay = page.locator(".hc").getByRole("button", { name: hc.controls.replay })
    await expect(pause).toHaveCount(1)
    await expect(pause).toHaveText(hc.controls.pause)
    await expect(replay).toBeVisible()
    const figure = (await page.locator(".hc").boundingBox())!
    for (const button of [pause, replay]) {
      const box = (await button.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      expect(box.y + box.height).toBeGreaterThan(figure.y + figure.height - 50)
      expect(box.x).toBeGreaterThan(figure.x + figure.width / 2)
    }
    // A hairline brightens while its chip runs, and the family dinner lands.
    await expect.poll(() => opacity(page, '.hc-wide .hc-lit path[data-source="personal"]'), { timeout: 4000 }).toBeGreaterThan(0.5)
    await expect.poll(() => opacity(page, block("wide", "family")), { timeout: 9000 }).toBe(1)
    // Replay starts the cycle over: the day is empty again at once.
    await replay.click()
    expect(await opacity(page, block("wide", "family"))).toBe(0)
    await pause.click()
    await expect(page.locator(".hc")).toHaveAttribute("data-playing", "false")
    await expect(page.locator(".hc").getByRole("button", { name: en.motion.play })).toHaveText(hc.controls.play)
    await expect.poll(async () => (await run(page)).filter((animation) => animation.state === "running").length).toBe(0)
    await page.locator(".hc").getByRole("button", { name: en.motion.play }).click()
    await expect.poll(async () => (await run(page)).filter((animation) => animation.state === "running").length).toBeGreaterThan(0)
  })

  test("centres the switch, the ghost, and the page on one axis", async ({ page }) => {
    await page.goto("/home/hero-e4")
    const views = (await page.getByRole("group", { name: hc.viewLabel }).boundingBox())!
    const ghost = (await page.locator(".hc-wide .hc-ghost").boundingBox())!
    const figure = (await page.locator(".hc").boundingBox())!
    const axis = figure.x + figure.width / 2
    expect(Math.abs(views.x + views.width / 2 - axis)).toBeLessThan(2)
    expect(Math.abs(ghost.x + ghost.width / 2 - axis)).toBeLessThan(2)
  })

  test("off screen, the loop holds", async ({ page }) => {
    await page.goto("/home/hero-e4")
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.locator(".hc")).toHaveAttribute("data-offscreen", "")
    await expect.poll(async () => (await run(page)).filter((animation) => animation.state === "running").length).toBe(0)
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect.poll(async () => (await run(page)).filter((animation) => animation.state === "running").length).toBeGreaterThan(0)
  })

  test("the switch over the whole diagram turns the day into Sam's Personal calendar, every title kept, nothing held back, and back", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/home/hero-e4")
    const views = page.getByRole("group", { name: hc.viewLabel })
    const work = views.getByRole("button", { name: en.demo.workSees })
    const you = views.getByRole("button", { name: en.demo.youSee })
    await expect(work).toHaveAttribute("aria-pressed", "true")
    for (const button of [work, you]) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    // It sits over the whole diagram, centred.
    const figure = (await page.locator(".hc").boundingBox())!
    const group = (await views.boundingBox())!
    expect(Math.abs(group.x + group.width / 2 - (figure.x + figure.width / 2))).toBeLessThan(4)
    expect(group.y + group.height).toBeLessThanOrEqual((await page.locator(".hc-wide .hc-svg").boundingBox())!.y + 1)

    await you.click()
    await expect(page.locator(".hc")).toHaveAttribute("data-view", "you")
    expect(await opacity(page, ".hc-wide .hc-head.hc-as-you")).toBe(1)
    await expect(page.locator(".hc-wide .hc-head.hc-as-you")).toContainText(en.app.rules.accounts.personal)
    expect(await opacity(page, ".hc-wide .hc-label.hc-as-you")).toBe(1)
    await expect(page.locator(".hc-wide .hc-label.hc-as-you")).toHaveText(hc.dayLabels.you)
    await expect(page.locator(`${block("wide", "personal")} .hc-as-you`)).toHaveText(new RegExp(`^${gym}\\s*12:00–13:00$`))
    await expect(page.locator(`${block("wide", "family")} .hc-as-you`)).toHaveText(new RegExp(`^${dinner}\\s*18:00–19:00$`))
    expect(await opacity(page, `${block("wide", "personal")} .hc-as-work`)).toBe(0)
    expect(await opacity(page, ".hc-wide .hc-kept")).toBe(0)

    await work.click()
    await expectWorkSees(page, "wide")
    await context.close()
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: Work in a calm red, Busy in Lantern Indigo, and the ghost ${scheme === "light" ? "filled indigo, without a halo" : "white and glowing"}`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e4")
      const ring = await page.locator('.hc-wide .hc-pill[data-calendar="work"] .hc-ring').evaluate((element) => getComputedStyle(element).stroke)
      const [r, g, b] = await rgb(page, ring)
      expect(r).toBeGreaterThan(g + 40)
      expect(r).toBeGreaterThan(b + 40)
      await expect(page.locator(`${block("wide", "work")} .hc-source-dot`)).toHaveCSS("fill", ring)
      const primary = await page.locator(".hh-accent").evaluate((element) => getComputedStyle(element).color)
      for (const title of await page.locator('.hc-wide .hc-block[data-shows="busy"] .hc-as-work .hc-block-title').all()) await expect(title).toHaveCSS("fill", primary)
      const ghost = page.locator(".hc-wide .hc-ghost .ghost")
      const body = await rgb(page, await ghost.locator(".ghost-body").evaluate((element) => getComputedStyle(element).fill))
      const glow = await ghost.evaluate((element) => getComputedStyle(element, "::before").backgroundColor)
      if (scheme === "light") {
        expect(body[0] + body[1] + body[2]).toBeLessThan(620)
        expect(body[2]).toBeGreaterThan(body[0] + 30)
        expect(glow).toBe("rgba(0, 0, 0, 0)")
      } else {
        expect(Math.min(...body)).toBeGreaterThan(220)
        expect(glow).not.toBe("rgba(0, 0, 0, 0)")
      }
      const width = (await ghost.boundingBox())!.width
      expect(width).toBeGreaterThanOrEqual(88)
      expect(width).toBeLessThanOrEqual(104)
      await context.close()
    })
  }

  test("tells screen readers what work sees of each event, and what Sam sees instead, and hides the drawing from them", async ({ page }) => {
    await page.goto("/home/hero-e4")
    const figure = page.getByRole("figure", { name: hc.summary })
    await expect(figure.locator("ul.sr-only li")).toHaveText([
      "Gym from Personal appears on Work as Busy, from 12:00 to 13:00.",
      "Client call, Work's own meeting, shows with its title, from 14:30 to 15:30.",
      "Family dinner from Family appears on Work as Busy, from 18:00 to 19:00.",
      hc.never,
      hc.youFact,
    ])
    for (const svg of await page.locator(".hc .hc-svg").all()) await expect(svg).toHaveAttribute("aria-hidden", "true")
  })

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the diagram runs down, inside the page: the switch, the calendars, the ghost, then the day`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/home/hero-e4")
      await expect(page.locator(".hc-wide")).toBeHidden()
      const tall = page.locator(".hc-tall")
      const box = (await tall.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      const views = (await page.getByRole("group", { name: hc.viewLabel }).boundingBox())!
      const pills = await Promise.all((await tall.locator(".hc-pill").all()).map(async (item) => (await item.boundingBox())!))
      const ghost = (await tall.locator(".hc-ghost").boundingBox())!
      const day = (await tall.locator(".hc-day .hc-box").boundingBox())!
      expect(views.x).toBeGreaterThanOrEqual(0)
      expect(views.x + views.width).toBeLessThanOrEqual(width)
      expect(views.y + views.height).toBeLessThanOrEqual(Math.min(...pills.map((pill) => pill.y)))
      expect(Math.max(...pills.map((pill) => pill.y + pill.height))).toBeLessThan(ghost.y)
      expect(ghost.y + ghost.height).toBeLessThan(day.y)
      // The pills in one tidy row, the same height, side by side and apart.
      for (const pill of pills) expect(Math.abs(pill.y - pills[0]!.y)).toBeLessThan(1)
      for (const [index, pill] of pills.slice(1).entries()) expect(pill.x).toBeGreaterThan(pills[index]!.x + pills[index]!.width)
      // What the ghost keeps back, centred under it, above the day, touching nothing else.
      const kept = await Promise.all((await tall.locator(".hc-kept-title rect").all()).map(async (item) => (await item.boundingBox())!))
      const ghostMiddle = ghost.x + ghost.width / 2
      for (const chip of kept) {
        expect(Math.abs(chip.x + chip.width / 2 - ghostMiddle)).toBeLessThan(2)
        expect(chip.y).toBeGreaterThan(ghost.y + ghost.height * 0.8)
        expect(chip.y + chip.height).toBeLessThan(day.y)
      }
      await expectWorkSees(page, "tall")
      await context.close()
    })
  }
})

test.describe("the display face", () => {
  const families = (page: Page) => page.evaluate(() => [...document.fonts].map((font) => font.family.replaceAll('"', "")))

  for (const path of ["/", "/bold", "/home/hero-e4", "/docs/self-hosting"]) {
    test(`${path}: every heading is set in Besley, preloaded, at its natural spacing`, async ({ page }) => {
      await page.goto(path)
      const preloads = await page.locator('link[rel="preload"][as="font"]').evaluateAll((links) => links.map((link) => link.getAttribute("href")))
      expect(preloads.some((href) => href?.includes("besley-latin-wght-normal"))).toBe(true)
      for (const heading of [page.locator("h1").first(), page.locator("main h2").first()]) {
        const style = await heading.evaluate((element) => {
          const computed = getComputedStyle(element)
          return { family: computed.fontFamily, tracking: computed.letterSpacing, size: parseFloat(computed.fontSize), leading: parseFloat(computed.lineHeight) }
        })
        expect(style.family).toMatch(/^"?Besley Variable/)
        // Never tightened: Besley's letters touch at negative tracking.
        expect(style.tracking === "normal" || parseFloat(style.tracking) >= 0, style.tracking).toBe(true)
        // Room between lines for its tall ascenders.
        expect(style.leading / style.size).toBeGreaterThanOrEqual(1.04)
      }
      // The calibration picker and the faces only it used are gone.
      await expect(page.locator("[data-display-font-picker]")).toHaveCount(0)
      expect((await families(page)).some((family) => /Fraunces|Bricolage/.test(family))).toBe(false)
    })
  }
})

test.describe("the versions index", () => {
  const listed = VERSIONS.flatMap((version) => version.iterations)

  test("every live route it lists responds, a discarded one is gone, and only production is in the sitemap", async ({ request }) => {
    const sitemap = await (await request.get("/sitemap-0.xml")).text()
    for (const { path, status } of listed) {
      if (status === "discarded") {
        expect((await request.get(path)).status(), path).toBe(404)
        expect(sitemap, path).not.toContain(`calendarghost.com${path}<`)
        continue
      }
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
        await expect(group).toContainText(iteration.commit)
        if (iteration.status === "discarded") {
          // No live link: the entry says how to see it with git instead.
          await expect(group.getByRole("link", { name: iteration.name })).toHaveCount(0)
          const entry = group.getByRole("listitem").filter({ hasText: iteration.name })
          await expect(entry.locator(".versions-status")).toHaveText(STATUS_LABELS.discarded)
          await expect(entry).toContainText(VIEW_WITH_GIT)
          await expect(entry).toContainText(`git worktree add ../calendar-ghost-${iteration.commit} ${iteration.commit}`)
          continue
        }
        const link = group.getByRole("link", { name: iteration.name })
        await expect(link).toHaveAttribute("href", iteration.path)
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
      // The link sits in the iteration tools' fixed corner.
      expect(await link.evaluate((element) => getComputedStyle(element.closest(".iteration-tools") ?? element).position)).toBe("fixed")
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    await page.goto("/")
    await expect(page.getByRole("link", { name: VERSIONS_LINK_LABEL, exact: true })).toHaveCount(0)
  })
})
