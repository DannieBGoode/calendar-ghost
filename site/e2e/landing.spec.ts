import { expect, test, type Page } from "@playwright/test"
import { DOC_PAGES, docPagePath } from "../src/docs/pages"
import { en } from "../src/i18n/en"
import { SELF_HOST_COMMANDS } from "../src/content/self-host"
import {
  CHANGELOG_URL,
  DOCS_URL,
  GUIDE_URL,
  INTEGRATIONS_URL,
  LICENSE_URL,
  REPO_URL,
  TRADEMARKS_URL,
  TRUST_DOCS,
} from "../src/links"

/** The home page's section headings, in order, which a visitor finds without JavaScript. */
const HEADINGS = [
  en.how.title,
  en.compatibleCalendars.title,
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

test("compatible calendars distinguish available and planned providers on desktop and mobile", async ({ browser }) => {
  for (const width of [1280, 1024, 768, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto("/")
    const section = page.getByRole("region", { name: en.compatibleCalendars.title })
    await section.scrollIntoViewIfNeeded()
    await expect(section).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    const google = section.getByRole("listitem").filter({ hasText: en.compatibleCalendars.google.name })
    const outlook = section.getByRole("listitem").filter({ hasText: en.compatibleCalendars.outlook.name })
    const icloud = section.getByRole("listitem").filter({ hasText: en.compatibleCalendars.icloud.name })
    await expect(google.getByText(en.compatibleCalendars.google.status, { exact: true })).toBeVisible()
    await expect(outlook.getByText(en.compatibleCalendars.outlook.status, { exact: true })).toBeVisible()
    await expect(icloud.getByText(en.compatibleCalendars.icloud.status, { exact: true })).toBeVisible()
    expect(await section.getByRole("link").count()).toBe(0)
    const first = (await google.boundingBox())!
    const second = (await outlook.boundingBox())!
    expect(Math.abs(first.y - second.y)).toBeLessThan(1)
    for (const box of [first, second, (await icloud.boundingBox())!]) {
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
    }
    await context.close()
  }
})

test("upcoming provider marks regain color on desktop hover and stay colored on touch devices", async ({ browser }) => {
  for (const [width, hasTouch] of [[1280, false], [390, true], [1024, true]] as const) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch, reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/")
    const section = page.locator("#compatible-calendars")
    await section.scrollIntoViewIfNeeded()
    await expect(section.locator(".calendar-google")).toHaveCSS("filter", "none")
    for (const mark of await section.locator(".calendar-float.is-unavailable, .calendar-provider.is-unavailable .calendar-mark").all()) {
      await expect(mark).toHaveCSS("filter", hasTouch ? "none" : "grayscale(1)")
      if (!hasTouch) {
        await mark.hover()
        await expect(mark).toHaveCSS("filter", "grayscale(0)")
        await page.mouse.move(0, 0)
        await expect(mark).toHaveCSS("filter", "grayscale(1)")
      }
    }
    await context.close()
  }
})

test("provider motion loops, pauses, and respects reduced motion", async ({ browser }) => {
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    const context = await browser.newContext({ reducedMotion })
    const page = await context.newPage()
    await page.goto("/")
    const scene = page.locator("#compatible-calendars")
    await scene.scrollIntoViewIfNeeded()
    await expect(scene).toHaveAttribute("data-enhanced", "")
    const running = () => scene.evaluate((element) => element.getAnimations({ subtree: true }).filter((animation) => animation.playState === "running").length)
    if (reducedMotion === "reduce") {
      expect(await running()).toBe(0)
      await expect(scene.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
    }
    else {
      await expect.poll(running).toBe(3)
      expect(await scene.evaluate((element) => element.getAnimations({ subtree: true }).every((animation) => animation.effect?.getTiming().iterations === Infinity))).toBe(true)
      expect(await scene.locator(".calendars-list").evaluate((element) => element.getAnimations({ subtree: true }).length)).toBe(0)
      await scene.getByRole("button", { name: en.motion.pause }).click()
      await expect.poll(running).toBe(0)
      await scene.getByRole("button", { name: en.motion.play }).click()
      await expect.poll(running).toBe(3)
      await page.evaluate(() => scrollTo(0, 0))
      await expect(scene).toHaveAttribute("data-offscreen", "")
      await expect.poll(running).toBe(0)
      await scene.scrollIntoViewIfNeeded()
      await expect.poll(running).toBe(3)
    }
    await context.close()
  }
})

/** Scrolls through the whole page so every island hydrates and every once-only scene wakes. */
async function visitEverything(page: Page) {
  const height = await page.evaluate(() => document.body.scrollHeight)
  for (let top = 0; top < height; top += 400) {
    await page.evaluate((y) => window.scrollTo(0, y), top)
    await page.waitForTimeout(60)
  }
}

/** Every CSS animation on the page, with whether a demo's pause control governs it. */
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

test("loads nothing from another host", async ({ page, baseURL }) => {
  const foreign: string[] = []
  const host = new URL(baseURL!).host
  page.on("request", (request) => {
    if (new URL(request.url()).host !== host) foreign.push(request.url())
  })
  await page.goto("/")
  await visitEverything(page)
  await page.waitForLoadState("networkidle")
  expect(foreign).toEqual([])
})

test("is indexed, and the sitemap lists the home page and the documentation pages, nothing else", async ({ page, request }) => {
  await page.goto("/")
  await expect(page.locator('meta[name="robots"]')).toHaveCount(0)
  const sitemap = await (await request.get("/sitemap-0.xml")).text()
  const listed = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1])
  const expected = ["/", ...DOC_PAGES.map((doc) => `${docPagePath(doc.slug)}/`)].map((path) => `https://calendarghost.com${path}`)
  expect(listed.sort()).toEqual(expected.sort())
})

test("an unknown address shows the ghost's own not-found page, not indexed", async ({ page }) => {
  const response = await page.goto("/nothing-here")
  expect(response!.status()).toBe(404)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.notFound.title)
  await expect(page.getByRole("link", { name: en.notFound.home })).toHaveAttribute("href", "/")
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "noindex")
})

test("with reduced motion, nothing moves by itself", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" })
  const page = await context.newPage()
  await page.goto("/")
  await visitEverything(page)
  await page.waitForTimeout(400)
  expect((await animations(page)).filter((animation) => animation.state === "running")).toEqual([])
  await expect(page.getByRole("button", { name: en.motion.pause, exact: true })).toHaveCount(0)
  await context.close()
})

test("the nav's section links stay on the page and land on their sections", async ({ page }) => {
  await page.goto("/")
  const hrefs = await page.locator("nav .nav-wide a").evaluateAll((links) => links.map((link) => link.getAttribute("href")))
  expect(hrefs.length).toBeGreaterThan(0)
  for (const href of hrefs) {
    expect(href).toMatch(/^\/#/)
    await expect(page.locator(`#${href!.split("#")[1]}`)).toHaveCount(1)
  }
})

test("without JavaScript, the content and the hero's resting state are there", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.hero.titleLines.join(" "))
  await expect(page.locator(".hc-static-view")).toHaveText(en.demo.workSees)
  for (const heading of HEADINGS) await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible()
  await expect(page.getByText(en.faq.items[0]!.q)).toBeVisible()
  await expect(page.getByRole("img", { name: en.app.overview.alt })).toBeVisible()
  await expect(page.locator('button[data-copy="self-host-commands"]')).toBeHidden()
  await expect(page.locator(".crossing-stage .crossing-landed").getByText(en.demo.busy)).toBeVisible()
  await expect(page.locator(".crossing-stays").getByText(en.crossing.alwaysStays[0])).toBeVisible()
  // No CSS state gates the bubble without JavaScript: the ghost just says the resting line.
  await expect(page.locator(".crossing-says")).toHaveText(en.ghost.crossingBusy)
  await expect(page.locator("#how-it-works .how-preview-row").first()).toContainText(en.demo.busy)
  // Nothing loops without JavaScript, so there is nothing to pause.
  await expect(page.getByRole("button", { name: en.motion.pause, exact: true })).toHaveCount(0)
  await context.close()
})

test.describe("the hero", () => {
  const hc = en.hero.diagram
  const emoji = hc.emoji
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
  const runningCount = async (page: Page) => (await run(page)).filter((animation) => animation.state === "running").length
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
    await expect(page.locator(`${block(layout, "work")} text`)).toHaveText(new RegExp(`^${emoji.clientCall}\\s*${call}\\s*14:30–15:30$`))
    await expect(page.locator(`${block(layout, "personal")} text.hc-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*12:00–13:00$`))
    await expect(page.locator(`${block(layout, "family")} text.hc-as-work`)).toHaveText(new RegExp(`^${en.demo.busy}\\s*18:00–19:00$`))
    expect(await opacity(page, `.hc-${layout} .hc-head.hc-as-work`)).toBe(1)
    await expect(page.locator(`.hc-${layout} .hc-kept-caption`)).toHaveText(hc.kept)
    await expect(page.locator(`.hc-${layout} .hc-kept-title`)).toHaveText([gym, dinner])
    expect(await opacity(page, `.hc-${layout} .hc-kept`)).toBe(1)
    for (const title of await page.locator(`.hc-${layout} .hc-kept-title`).all()) await expect(title).toHaveCSS("opacity", "1")
  }

  for (const [width, height] of [
    [1280, 800],
    [1024, 768],
  ] as const) {
    test(`at ${width}x${height}, the headline, the line, the calls to action, and the diagram's switch fit the first screen`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/")
      for (const selector of ["h1", ".hero-line", ".hero-ctas", ".hc-views"]) {
        const box = (await page.locator(selector).first().boundingBox())!
        expect(box.y, selector).toBeGreaterThanOrEqual(0)
        expect(box.y + box.height, selector).toBeLessThanOrEqual(height)
      }
      await expect(page.locator(".hero-line")).toHaveText(en.hero.line)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await context.close()
    })
  }

  test("on a phone, the headline, the call to action, and the diagram's switch fit the first screen", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/")
    await expect(page.getByRole("heading", { level: 1 })).toBeInViewport()
    await expect(page.getByRole("link", { name: en.hero.primary }).first()).toBeInViewport()
    await expect(page.getByRole("group", { name: hc.viewLabel })).toBeInViewport()
    await context.close()
  })

  test("without JavaScript or with reduced motion: everything has landed, as work sees it, and nothing moves", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options })
      const page = await context.newPage()
      await page.goto("/")
      expect(await runningCount(page)).toBe(0)
      await expect(page.locator(".hc-wide .hc-pill")).toHaveText([
        new RegExp(`${en.demo.calendars.personal}\\s*${emoji.gym}\\s*${gym} 12:00`),
        new RegExp(`${en.demo.calendars.work}\\s*${emoji.clientCall}\\s*${call} 14:30`),
        new RegExp(`${en.demo.calendars.family}\\s*${emoji.familyDinner}\\s*${dinner} 18:00`),
      ])
      await expect(page.locator(".hc-wide .hc-label").first()).toHaveText(hc.calendarsLabel)
      await expect(page.locator(".hc-wide .hc-label.hc-as-work")).toHaveText(hc.dayLabels.work)
      await expectWorkSees(page, "wide")
      for (const chip of await page.locator(".hc-wide .hc-chip").all()) await expect(chip).toHaveCSS("opacity", "0")
      for (const ripple of await page.locator(".hc-wide .hc-ripple").all()) await expect(ripple).toHaveCSS("opacity", "0")
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

  test("loops calmly, with a small labelled Pause and Replay in the diagram's bottom-right corner", async ({ page }) => {
    await page.goto("/")
    const animations = await run(page)
    expect(animations.length).toBeGreaterThan(10)
    for (const animation of animations) expect(animation.iterations, animation.name).toBe(Infinity)
    const pause = page.locator(".hc").getByRole("button", { name: en.motion.pause })
    const replay = page.locator(".hc").getByRole("button", { name: hc.replay })
    await expect(pause).toHaveCount(1)
    await expect(pause).toHaveText(en.motion.pauseShort)
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
    await expect(page.locator(".hc").getByRole("button", { name: en.motion.play })).toHaveText(en.motion.playShort)
    await expect.poll(() => runningCount(page)).toBe(0)
    await page.locator(".hc").getByRole("button", { name: en.motion.play }).click()
    await expect.poll(() => runningCount(page)).toBeGreaterThan(0)
  })

  test("each calendar is a portrait in its ring, its name and event flush to its left (below it on a phone), and it pops as its event leaves", async ({ browser }) => {
    for (const [layout, width] of [["wide", 1280], ["tall", 390]] as const) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      await page.goto("/")
      for (const pill of await page.locator(`.hc-${layout} .hc-pill`).all()) {
        const ring = (await pill.locator(".hc-ring").boundingBox())!
        const text = (await pill.locator("text").boundingBox())!
        if (layout === "wide") {
          expect(text.x + text.width).toBeLessThan(ring.x)
          expect(ring.x - (text.x + text.width)).toBeLessThan(20)
          expect(Math.abs(text.y + text.height / 2 - (ring.y + ring.height / 2))).toBeLessThan(4)
        } else {
          expect(text.y).toBeGreaterThan(ring.y + ring.height - 2)
        }
      }
      const names = (await run(page)).map((animation) => animation.name)
      expect(names.filter((name) => name.startsWith(`hc-${layout}-pop-`))).toHaveLength(3)
      expect(names.filter((name) => name.startsWith(`hc-${layout}-ripple-`))).toHaveLength(3)
      await context.close()
    }
  })

  test("centres the switch, the ghost, and the page on one axis", async ({ page }) => {
    await page.goto("/")
    const views = (await page.getByRole("group", { name: hc.viewLabel }).boundingBox())!
    const ghost = (await page.locator(".hc-wide .hc-ghost").boundingBox())!
    const figure = (await page.locator(".hc").boundingBox())!
    const axis = figure.x + figure.width / 2
    expect(Math.abs(views.x + views.width / 2 - axis)).toBeLessThan(2)
    expect(Math.abs(ghost.x + ghost.width / 2 - axis)).toBeLessThan(2)
  })

  test("off screen, the loop holds", async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    await expect(page.locator(".hc")).toHaveAttribute("data-offscreen", "")
    await expect.poll(() => runningCount(page)).toBe(0)
    await page.evaluate(() => window.scrollTo(0, 0))
    await expect.poll(() => runningCount(page)).toBeGreaterThan(0)
  })

  test("the switch over the whole diagram turns the day into Sam's Personal calendar, every title kept, nothing held back, and back", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" })
    const page = await context.newPage()
    await page.goto("/")
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
    await expect(page.locator(`${block("wide", "personal")} text.hc-as-you`)).toHaveText(new RegExp(`^${emoji.gym}\\s*${gym}\\s*12:00–13:00$`))
    await expect(page.locator(`${block("wide", "family")} text.hc-as-you`)).toHaveText(new RegExp(`^${emoji.familyDinner}\\s*${dinner}\\s*18:00–19:00$`))
    expect(await opacity(page, `${block("wide", "personal")} text.hc-as-work`)).toBe(0)
    expect(await opacity(page, ".hc-wide .hc-kept")).toBe(0)

    await work.click()
    await expectWorkSees(page, "wide")
    await context.close()
  })

  test("the switch works from the keyboard", async ({ page }) => {
    await page.goto("/")
    const views = page.getByRole("group", { name: hc.viewLabel })
    await views.getByRole("button", { name: en.demo.youSee }).focus()
    await page.keyboard.press("Enter")
    await expect(page.locator(".hc")).toHaveAttribute("data-view", "you")
    await page.keyboard.press("Shift+Tab")
    await expect(views.getByRole("button", { name: en.demo.workSees })).toBeFocused()
    await page.keyboard.press("Space")
    await expect(page.locator(".hc")).toHaveAttribute("data-view", "work")
    await expect(views.getByRole("button", { name: en.demo.workSees })).toHaveAttribute("aria-pressed", "true")
  })

  for (const scheme of ["light", "dark"] as const) {
    test(`in ${scheme}: Work in a calm red, Busy in Lantern Indigo, and the ghost ${scheme === "light" ? "filled indigo, without a halo" : "white and glowing"}`, async ({ browser }) => {
      const context = await browser.newContext({ colorScheme: scheme, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/")
      const ring = await page.locator('.hc-wide .hc-pill[data-calendar="work"] .hc-ring').evaluate((element) => getComputedStyle(element).stroke)
      const [r, g, b] = await rgb(page, ring)
      expect(r).toBeGreaterThan(g + 40)
      expect(r).toBeGreaterThan(b + 40)
      await expect(page.locator(`${block("wide", "work")} .hc-source-dot`)).toHaveCSS("fill", ring)
      const primary = await page.locator(".hero-accent").evaluate((element) => getComputedStyle(element).color)
      for (const title of await page.locator('.hc-wide .hc-block[data-shows="busy"] .hc-as-work .hc-block-title').all()) await expect(title).toHaveCSS("fill", primary)
      // Busy is hatched, as time that is taken with nothing to read; Work's own meeting is not.
      await expect(page.locator('.hc-wide .hc-block[data-shows="busy"] .hc-hatch')).toHaveCount(2)
      await expect(page.locator(`${block("wide", "work")} .hc-hatch`)).toHaveCount(0)
      const ghost = page.locator(".hc-wide .hc-ghost .ghost")
      await expect(ghost).not.toHaveAttribute("data-tone", "moss")
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
    await page.goto("/")
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

  for (const [layout, width] of [
    ["wide", 1440],
    ["tall", 390],
  ] as const) {
    test(`${layout}: an emoji before every title it shows, the ghost glyph wherever a title is hidden`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/")
      const diagram = page.locator(`.hc-${layout}`)
      // The facts list reads the titles without their emoji.
      for (const mark of Object.values(emoji)) await expect(page.locator(".hc ul.sr-only")).not.toContainText(mark)
      const pills = diagram.locator(".hc-pill text")
      await expect(pills.nth(0)).toContainText(`${emoji.gym} ${gym}`)
      await expect(pills.nth(1)).toContainText(`${emoji.clientCall} ${call}`)
      await expect(pills.nth(2)).toContainText(`${emoji.familyDinner} ${dinner}`)
      // Work's own meeting keeps its emoji; each Busy block and each kept title carries the glyph.
      await expect(diagram.locator('.hc-block[data-shows="own"]')).toContainText(emoji.clientCall)
      for (const item of await diagram.locator('.hc-block[data-shows="busy"]').all()) await expect(item.locator(".hc-glyph")).toHaveCount(1)
      for (const kept of await diagram.locator(".hc-kept-title").all()) await expect(kept.locator(".hc-glyph")).toHaveCount(1)
      // The chips carry the emoji on their way in, and the Busy chips after the ghost carry the glyph.
      for (const chip of await diagram.locator('.hc-chip[data-side="in"]').all()) await expect(chip).toContainText(/ /)
      for (const chip of await diagram.locator('.hc-chip[data-side="out"][data-shows="busy"]').all()) await expect(chip.locator(".hc-glyph")).toHaveCount(1)
      await context.close()
    })
  }

  for (const [width, height] of [
    [390, 844],
    [320, 740],
  ] as const) {
    test(`at ${width}px the diagram runs down, inside the page: the switch, the calendars, the ghost, then the day`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/")
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

test("every self-running demo has a pause control a finger can hit, and pausing stops it", async ({ page }) => {
  await page.goto("/")
  await visitEverything(page)
  // The hero's diagram, the provider cluster, the Haunted Week, and the Crossing.
  const buttons = page.getByRole("button", { name: en.motion.pause, exact: true })
  await expect(buttons).toHaveCount(4)
  for (const button of await buttons.all()) expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  // Each click turns a Pause button into Play, so the first Pause left is always the next one.
  for (let loop = 0; loop < 4; loop += 1) {
    await buttons.first().scrollIntoViewIfNeeded()
    await buttons.first().click()
  }
  await expect(page.getByRole("button", { name: en.motion.play, exact: true })).toHaveCount(4)
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

/** The animations running under `selector` (its own and its pseudo-elements'), counted. */
const running = (page: Page, selector: string) =>
  page.locator(selector).evaluate((element) =>
    document
      .getAnimations()
      .filter((animation) => {
        const target = (animation.effect as KeyframeEffect | null)?.target
        return animation.playState === "running" && target instanceof Element && (target === element || element.contains(target))
      }).length,
  )

/** The longest any animation under `selector` runs, from its start, in milliseconds. */
const longest = (page: Page, selector: string) =>
  page.locator(selector).evaluate((element) =>
    Math.max(
      0,
      ...document
        .getAnimations()
        .filter((animation) => {
          const target = (animation.effect as KeyframeEffect | null)?.target
          return target instanceof Element && (target === element || element.contains(target))
        })
        .map((animation) => Number(animation.effect?.getComputedTiming().endTime ?? 0)),
    ),
  )

test("the decorative loops play for at most five seconds each time they come into view, then again on the next visit", async ({ page }) => {
  await page.goto("/")
  for (const selector of [".footer-watch .ghost", ".mock-health .ghost", "#integrations .watch", "#integrations .int-mon"]) {
    await page.locator(selector).scrollIntoViewIfNeeded()
    await expect.poll(() => running(page, selector), { message: selector }).toBeGreaterThan(0)
    expect(await longest(page, selector), selector).toBeLessThanOrEqual(5000)
  }
  // The footer's sleeper settles, then wakes again when it comes back into view.
  const sleeper = ".footer-watch .ghost"
  await page.locator(sleeper).scrollIntoViewIfNeeded()
  await expect.poll(() => running(page, sleeper), { timeout: 7000 }).toBe(0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect(page.locator(".footer-watch .ghost")).not.toHaveAttribute("data-awake")
  await page.locator(sleeper).scrollIntoViewIfNeeded()
  await expect.poll(() => running(page, sleeper)).toBeGreaterThan(0)
})

test("there is no site-wide animations control, and the footer keeps only the license link", async ({ page }) => {
  for (const path of ["/", "/docs/self-hosting"]) {
    await page.goto(path)
    await expect(page.getByRole("button", { name: /animations/i })).toHaveCount(0)
    await expect(page.locator(".flinks")).not.toContainText("GNU AGPL, version 3")
    await expect(page.locator(".flinks").getByRole("link", { name: en.footer.licenseLink })).toHaveCount(1)
  }
  expect(await page.evaluate(() => localStorage.getItem("calendar-ghost-site-motion"))).toBeNull()
})

test("at 320px the nav fits the name, the menu, and the theme toggle", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 320, height: 640 } })
  const page = await context.newPage()
  await page.goto("/")
  const brand = page.locator(".nav-brand span")
  await expect(brand).toBeVisible()
  const theme = (await page.locator("[data-theme-toggle]").boundingBox())!
  const menu = (await page.locator(".nav-narrow summary").boundingBox())!
  const name = (await brand.boundingBox())!
  expect(name.x + name.width).toBeLessThanOrEqual(menu.x)
  expect(theme.x + theme.width).toBeLessThanOrEqual(320)
  await context.close()
})

for (const width of [320, 390]) {
  test(`nothing scrolls sideways on a ${width}px screen`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 740 } })
    const page = await context.newPage()
    await page.goto("/")
    await page.waitForLoadState("networkidle")
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await context.close()
  })
}

test("small controls are at least 44px tall", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const page = await context.newPage()
  await page.goto("/")
  await page.locator(".crossing").scrollIntoViewIfNeeded()
  const controls = [
    page.locator(".nav-narrow summary"),
    page.locator(".hc-view"),
    page.locator(".hc-motion button"),
    page.locator(".how-segment button"),
    page.locator(".crossing-switch button"),
    page.locator("button[data-copy]"),
    page.locator(".faq summary"),
    page.locator("[data-theme-toggle]"),
  ]
  for (const control of controls) {
    await expect(control.first()).toBeVisible()
    for (const item of await control.all()) expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await context.close()
})

test("the footer's dozing ghost mumbles in its sleep, over its head, then falls quiet", async ({ browser }) => {
  for (const options of [{}, { viewport: { width: 390, height: 844 } }]) {
    const context = await browser.newContext(options)
    const page = await context.newPage()
    await page.goto("/")
    const watch = page.locator(".footer-watch")
    await expect(watch.locator('.ghost[data-face="sleepy"]')).toHaveCount(1)
    await expect(watch.locator("p.footer-watch-note")).toHaveText(en.footer.watch)
    const bubble = watch.locator(".speech-bubble")
    await expect(bubble).toHaveText(en.footer.sleepTalk)
    await watch.scrollIntoViewIfNeeded()
    // It comes once the ghost has dozed off, over its head and inside the page.
    await expect(bubble).toBeVisible({ timeout: 4000 })
    await expect(bubble).toHaveCSS("opacity", "1")
    const box = (await bubble.boundingBox())!
    const ghost = (await watch.locator(".ghost").boundingBox())!
    expect(box.y + box.height).toBeLessThanOrEqual(ghost.y + ghost.height * 0.3)
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    // The still ghost rests without it.
    await expect(bubble).toBeHidden({ timeout: 4000 })
    await context.close()
  }
  // Without motion or JavaScript there is only the still ghost.
  for (const options of [{ reducedMotion: "reduce" as const }, { javaScriptEnabled: false }]) {
    const context = await browser.newContext(options)
    const page = await context.newPage()
    await page.goto("/")
    await page.locator(".footer-watch").scrollIntoViewIfNeeded()
    await expect(page.locator(".footer-watch .speech-bubble")).toBeHidden()
    await context.close()
  }
})

test("the How it works ghost first appears where its flight starts, so nothing jumps", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  const strip = page.locator(".how-strip")
  await expect(strip).not.toHaveAttribute("data-awake", "")
  const at = () =>
    strip.evaluate((element) => {
      const box = element.querySelector(".how-ghost .ghost")!.getBoundingClientRect()
      const track = element.querySelector(".how-track")!
      return { x: box.x, y: box.y, opacity: getComputedStyle(track).opacity }
    })
  const waiting = await at()
  // The flight's first frame: wake the strip, then hold every animation at time 0.
  await strip.evaluate((element) => {
    element.setAttribute("data-awake", "")
    for (const animation of element.getAnimations({ subtree: true })) {
      animation.pause()
      animation.currentTime = 0
    }
  })
  const first = await at()
  expect(Math.abs(first.x - waiting.x)).toBeLessThan(0.5)
  expect(Math.abs(first.y - waiting.y)).toBeLessThan(0.5)
  expect(first.opacity).toBe(waiting.opacity)
  // And the flight goes somewhere: its last frame is to the right.
  await strip.evaluate((element) => {
    for (const animation of element.getAnimations({ subtree: true })) animation.finish()
  })
  expect((await at()).x).toBeGreaterThan(waiting.x + 200)
})

test("without JavaScript or with reduced motion, the How it works ghost rests at the last step", async ({ browser }) => {
  for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...options })
    const page = await context.newPage()
    await page.goto("/")
    const ghost = (await page.locator(".how-ghost .ghost").boundingBox())!
    const last = (await page.locator(".how-steps li").nth(2).boundingBox())!
    expect(ghost.x).toBeGreaterThan(last.x)
    await context.close()
  }
})

test("a ghost that idles briefly wakes when it scrolls into view", async ({ page }) => {
  await page.goto("/")
  const sleeper = page.locator('.signature .ghost[data-alive="brief"]')
  await expect(sleeper).not.toHaveAttribute("data-awake", "")
  await sleeper.scrollIntoViewIfNeeded()
  await expect(sleeper).toHaveAttribute("data-awake", "")
})

test("Star on GitHub links open in a new tab and say so", async ({ page }) => {
  await page.goto("/")
  const stars = page.getByRole("link", { name: new RegExp(en.nav.star) })
  expect(await stars.count()).toBeGreaterThan(0)
  for (const star of await stars.all()) {
    await expect(star).toHaveAttribute("target", "_blank")
    await expect(star).toHaveAttribute("rel", "noopener noreferrer")
    await expect(star).toContainText(en.nav.newTab)
  }
})

test("self-hosting shows the three commands in one block, and its one Copy button selects them all without a clipboard", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
  await page.goto("/#self-host")
  const section = page.locator("#self-host")
  await expect(section.locator("button[data-copy]")).toHaveCount(1)
  await expect(section.locator("ol, ul, h3")).toHaveCount(0)
  await expect(section.getByText(en.selfHost.requirements)).toBeVisible()
  await expect(section.getByRole("link", { name: en.selfHost.guide })).toHaveAttribute("href", GUIDE_URL)
  await section.locator('button[data-copy="self-host-commands"]').click()
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe(SELF_HOST_COMMANDS.join("\n"))
  await expect(section.locator('button[data-copy="self-host-commands"]')).toHaveText(en.selfHost.selected)
})

test("the app mockups follow the dark color scheme", async ({ browser }) => {
  const background = async (colorScheme: "light" | "dark") => {
    const context = await browser.newContext({ colorScheme })
    const page = await context.newPage()
    await page.goto("/")
    const mockup = page.getByRole("img", { name: en.app.rules.alt })
    await mockup.scrollIntoViewIfNeeded()
    await expect(mockup).toBeVisible()
    // The rendered color, as sRGB channels, whatever color space the stylesheet used.
    const channels = await mockup.evaluate((element) => {
      const canvas = document.createElement("canvas").getContext("2d")!
      canvas.fillStyle = getComputedStyle(element).backgroundColor
      canvas.fillRect(0, 0, 1, 1)
      return Array.from(canvas.getImageData(0, 0, 1, 1).data.slice(0, 3))
    })
    await context.close()
    return channels.reduce((sum, channel) => sum + channel, 0) / 3
  }
  expect(await background("dark")).toBeLessThan(80)
  expect(await background("light")).toBeGreaterThan(200)
})

test("calendars show Sam's portraits, never letters", async ({ page }) => {
  await page.goto("/")
  // The demos hydrate when they scroll into view; their portraits come with them.
  for (const demo of [".haunt", ".crossing", ".mock-rules"]) await page.locator(demo).scrollIntoViewIfNeeded()
  const avatars = page.locator("img.avatar")
  await expect.poll(() => avatars.count()).toBeGreaterThanOrEqual(14)
  for (const avatar of await avatars.all()) {
    await avatar.scrollIntoViewIfNeeded()
    await expect(avatar).toHaveAttribute("alt", "")
    await expect.poll(() => avatar.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
  }
  await expect(page.locator(".mock-avatar")).toHaveCount(0)
  // The hero's diagram draws the same portraits inside its drawing.
  const portraits = await page.locator(".hc-wide image").evaluateAll((images) => images.map((image) => image.getAttribute("href") ?? ""))
  expect(portraits).toHaveLength(5)
  for (const href of portraits) expect(href).toMatch(/\/sam-(work|personal|family)\./)
})

test("each trust claim links to the documentation that proves it", async ({ page }) => {
  await page.goto("/")
  const links = page.locator("#trust a.doc-link")
  expect(await links.evaluateAll((all) => all.map((link) => link.getAttribute("href")))).toEqual([...TRUST_DOCS])
  for (const [index, link] of (await links.all()).entries()) {
    await expect(link).toContainText(en.trust.cards[index]!.title)
    await expect(link).toContainText(en.trust.docs)
  }
})

test("the nav's Features link lands on the app's features, and the trust list has its own anchor", async ({ page }) => {
  await page.goto("/")
  const link = page.locator("nav .nav-wide").getByRole("link", { name: en.nav.features, exact: true })
  await expect(link).toHaveAttribute("href", "/#features")
  await expect(page.locator("#features h2")).toHaveText(en.app.title)
  await expect(page.locator("#features .feat")).toHaveCount(3)
  await expect(page.locator("#trust h2")).toHaveText(en.trust.title)
})

test("monitors and agents come after the trust list: one sentence, three tools, one link", async ({ page }) => {
  await page.goto("/")
  const ids = await page.locator("main > section").evaluateAll((sections) => sections.map((section) => section.id))
  expect(ids.indexOf("integrations")).toBe(ids.indexOf("trust") + 1)
  expect(ids.indexOf("self-host")).toBe(ids.indexOf("integrations") + 1)
  const section = page.locator("#integrations")
  await expect(section.getByRole("heading", { level: 2 })).toHaveText(en.integrations.title)
  await expect(section.locator(".int-lead")).toHaveText(en.integrations.body)
  await expect(section.locator(".int-reader")).toHaveCount(3)
  // The setup's detail lives on the guide's page, not here.
  await expect(section.locator("a")).toHaveCount(1)
  await expect(section.getByRole("link", { name: en.integrations.guide })).toHaveAttribute("href", INTEGRATIONS_URL)
  await expect(section.locator("button[data-copy], pre, .int-caption")).toHaveCount(0)
})

test("the How it works switch changes what step 3's preview shows", async ({ page }) => {
  await page.goto("/")
  const strip = page.locator("#how-it-works")
  await strip.scrollIntoViewIfNeeded()
  const rows = strip.locator(".how-preview-row")
  await expect(rows.first()).toContainText(en.demo.busy)
  const details = strip.getByRole("button", { name: en.crossing.withDetails })
  await details.click()
  await expect(details).toHaveAttribute("aria-pressed", "true")
  await expect(rows.nth(0)).toContainText(en.demo.events.dentist.title)
  await expect(rows.nth(1)).toContainText(en.demo.events.gym.title)
  await expect(rows.nth(2)).toContainText(en.demo.events.therapy.title)
  await strip.getByRole("button", { name: en.crossing.busyOnly }).click()
  await expect(rows.first()).toContainText(en.demo.busy)
})

test("the crossing runs once, then rests on a clearly visible Busy on Work", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/")
  const crossing = page.locator(".crossing")
  await crossing.scrollIntoViewIfNeeded()
  await expect(crossing).toHaveAttribute("data-run", "running", { timeout: 3000 })
  // Still in flight: the ghost has not said anything yet.
  const bubble = crossing.locator(".crossing-says")
  expect(await bubble.evaluate((element) => getComputedStyle(element).opacity)).toBe("0")
  await expect(crossing).toHaveAttribute("data-run", "rested", { timeout: 7000 })
  const landed = crossing.locator(".crossing-work .crossing-landed")
  await expect(landed.getByText(en.demo.busy)).toBeVisible()
  expect(await landed.evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  expect(await landed.evaluate((element) => getComputedStyle(element).transform)).toBe("none")
  // A real fill and a solid edge, not a faint outline (drawn by the copy's card layer).
  const look = await landed.locator(".crossing-landed-box").evaluate((element) => {
    const style = getComputedStyle(element)
    return { edge: style.borderTopStyle, fill: style.backgroundColor }
  })
  expect(look.edge).toBe("solid")
  expect(look.fill).not.toMatch(/rgba\(.*, 0\)|transparent/)
  // Once it has landed, the ghost says so, tail pointing at it.
  await expect(bubble).toHaveText(en.ghost.crossingBusy)
  expect(await bubble.evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  // A new choice runs it again and lands the details.
  await crossing.getByRole("button", { name: en.crossing.withDetails }).click()
  await expect(crossing).toHaveAttribute("data-run", "running")
  await expect(crossing).toHaveAttribute("data-run", "rested", { timeout: 7000 })
  await expect(landed.getByText(en.demo.events.dentist.title)).toBeVisible()
  await expect(landed.getByText(en.demo.events.dentist.detail)).toBeVisible()
  await expect(bubble).toHaveText(en.ghost.crossingDetails)
})

for (const width of [390, 320]) {
  test(`at ${width}px: the carried card goes down the lane, covering nothing, not even Work's name, one label at a time, into the 15:00 slot`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto("/")
    const crossing = page.locator(".crossing")
    for (const mode of [en.crossing.busyOnly, en.crossing.withDetails]) {
      await crossing.scrollIntoViewIfNeeded()
      if (mode === en.crossing.withDetails) await crossing.getByRole("button", { name: mode }).click()
      await expect(crossing).toHaveAttribute("data-run", "running", { timeout: 3000 })
      const at = (time: number) =>
        crossing.evaluate((element, time) => {
          for (const animation of element.getAnimations({ subtree: true })) {
            animation.pause()
            animation.currentTime = time
          }
          const box = (selector: string) => element.querySelector(selector)!.getBoundingClientRect().toJSON() as DOMRect
          const shown = (selector: string) => {
            const style = getComputedStyle(element.querySelector(selector)!)
            return style.visibility === "hidden" ? 0 : Number(style.opacity)
          }
          // What Work's name draws (its portrait and its word), not the whole row it sits in.
          const name = document.createRange()
          name.selectNodeContents(element.querySelector(".crossing-work .crossing-name")!)
          return {
            card: box(".crossing-landed-box"),
            name: name.getBoundingClientRect().toJSON() as DOMRect,
            ghost: box(".crossing-ghost .ghost"),
            personal: box(".crossing-personal .crossing-event"),
            slot: box(".crossing-landed"),
            hour: box(".crossing-hour:nth-child(2)"),
            title: shown(".crossing-landed-title"),
            busy: shown(".crossing-landed-busy"),
          }
        }, time)
      // Out of the Personal card, in the lane: below the card and its chips, at the slot's size.
      for (const time of [0.3, 0.45, 0.55]) {
        const frame = await at(4800 * time)
        expect(frame.card.y, `${time}`).toBeGreaterThanOrEqual(frame.personal.y + frame.personal.height)
        expect(frame.ghost.y + frame.ghost.height * 0.5).toBeGreaterThanOrEqual(frame.personal.y + frame.personal.height)
        expect(Math.abs(frame.card.width - frame.slot.width)).toBeLessThan(1.5)
        // The ghost holds it from above, clear of the card's words.
        expect(frame.ghost.y + frame.ghost.height * 0.75).toBeLessThanOrEqual(frame.card.y + 2)
        // One label at a time.
        expect(Math.min(frame.title, frame.busy), `${time}: one label`).toBeLessThan(0.05)
      }
      // On its way down past Work's name, it never covers it.
      for (let time = 0.3; time <= 0.9; time += 0.05) {
        const { card, name } = await at(4800 * time)
        const overlaps = card.x < name.x + name.width && card.x + card.width > name.x && card.y < name.y + name.height && card.y + card.height > name.y
        expect(overlaps, `${time.toFixed(2)}: clear of Work's name`).toBe(false)
      }
      const landed = await at(4800 * 0.9)
      expect(Math.abs(landed.card.y - landed.slot.y)).toBeLessThan(1.5)
      expect(Math.abs(landed.card.y - landed.hour.y)).toBeLessThan(landed.hour.height / 2)
      await expect(crossing.locator(".crossing-landed-box")).toBeVisible()
      await crossing.evaluate((element) =>
        element
          .getAnimations({ subtree: true })
          .filter((animation) => animation.effect?.getComputedTiming().endTime !== Infinity)
          .forEach((animation) => animation.finish()),
      )
      await expect(crossing).toHaveAttribute("data-run", "rested", { timeout: 7000 })
    }
  })
}

for (const width of [1440, 1024]) {
  test(`at ${width}px: the carried card starts at the Dentist card's size and lands at the slot's, without a jump`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto("/")
    const crossing = page.locator(".crossing")
    await crossing.scrollIntoViewIfNeeded()
    await expect(crossing).toHaveAttribute("data-run", "running", { timeout: 3000 })
    /** The carried card's box and the box it should match, with every animation held at `at`. */
    const boxesAt = (at: number, target: string) =>
      crossing.evaluate(
        (element, [at, target]) => {
          for (const animation of element.getAnimations({ subtree: true })) {
            animation.pause()
            animation.currentTime = at as number
          }
          const box = (selector: string) => {
            const rect = element.querySelector(selector)!.getBoundingClientRect()
            return [rect.x, rect.y, rect.width, rect.height]
          }
          return { card: box(".crossing-landed-box"), target: box(target as string) }
        },
        [at, target] as const,
      )
    const expectSame = ({ card, target }: { card: number[]; target: number[] }) => {
      for (const [index, value] of card.entries()) expect(Math.abs(value - target[index]!)).toBeLessThan(1.5)
    }
    // 4.8s runs: the copy appears over the Dentist at 28% and is set down by 84%.
    expectSame(await boxesAt(4800 * 0.29, ".crossing-personal .crossing-source"))
    const landed = await boxesAt(4800 * 0.9, ".crossing-landed")
    expectSame(landed)
    // And on the way it is somewhere in between: never smaller than the slot, never larger
    // than the Dentist card.
    const midway = await boxesAt(4800 * 0.56, ".crossing-personal .crossing-source")
    expect(midway.card[2]!).toBeLessThan(midway.target[2]!)
    expect(midway.card[2]!).toBeGreaterThan(landed.target[2]!)
  })

  for (const colorScheme of ["light", "dark"] as const) {
    test(`at ${width}px ${colorScheme}: the crossing explains itself, with what stays behind on the Personal card`, async ({
      browser,
    }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce", colorScheme })
      const page = await context.newPage()
      await page.goto("/")
      const crossing = page.locator(".crossing")
      await crossing.scrollIntoViewIfNeeded()
      // The switch and its one line sit with the demo, on top of it.
      const bar = (await crossing.locator(".crossing-bar").boundingBox())!
      const personal = (await crossing.locator(".crossing-personal").boundingBox())!
      const work = (await crossing.locator(".crossing-work").boundingBox())!
      expect(bar.y + bar.height).toBeLessThanOrEqual(personal.y)
      await expect(crossing.locator(".crossing-explain")).toHaveText(en.crossing.busyOnlyBody)
      // Each part that never crosses over is a chip with its icon on the Personal card.
      const stays = crossing.locator(".crossing-personal .crossing-stays")
      await expect(stays.getByRole("heading", { name: en.crossing.alwaysStaysTitle })).toBeVisible()
      for (const item of en.crossing.alwaysStays) {
        const chip = stays.getByRole("listitem").filter({ hasText: item })
        await expect(chip).toBeVisible()
        await expect(chip.locator("svg")).toHaveCount(1)
      }
      if (width >= 1000) {
        // Side by side, close together, and large.
        expect(Math.abs(work.y - personal.y)).toBeLessThan(2)
        expect(work.x - (personal.x + personal.width)).toBeLessThan(160)
        expect(personal.width).toBeGreaterThan(420)
        expect(work.width).toBeGreaterThan(420)
      } else {
        // Stacked: Personal, then Work.
        expect(work.y).toBeGreaterThan(personal.y + personal.height)
      }
      // Under reduced motion it has simply landed.
      await expect(crossing).toHaveAttribute("data-run", "rested")
      await expect(crossing.locator(".crossing-landed").getByText(en.demo.busy)).toBeVisible()

      // The ghost's speech bubble rests beside it, tail pointing at it, saying the Busy-only
      // line, and never over Work's landed Busy block or the switch.
      const bubble = crossing.locator(".crossing-says")
      await expect(bubble).toBeVisible()
      await expect(bubble).toHaveAttribute("data-side", "top")
      await expect(bubble).toHaveText(en.ghost.crossingBusy)
      const overlaps = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
        a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y
      const landedBox = (await crossing.locator(".crossing-landed").boundingBox())!
      const switchBox = (await crossing.locator(".crossing-switch").boundingBox())!
      expect(overlaps((await bubble.boundingBox())!, landedBox)).toBe(false)
      expect(overlaps((await bubble.boundingBox())!, switchBox)).toBe(false)

      // A new choice changes what it says, and it still clears both.
      await crossing.getByRole("button", { name: en.crossing.withDetails }).click()
      await expect(bubble).toHaveText(en.ghost.crossingDetails)
      expect(overlaps((await bubble.boundingBox())!, (await crossing.locator(".crossing-landed").boundingBox())!)).toBe(false)
      expect(overlaps((await bubble.boundingBox())!, (await crossing.locator(".crossing-switch").boundingBox())!)).toBe(false)

      await context.close()
    })
  }
}

test("without JavaScript, the integrations mockups show their final state", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  await page.locator("#integrations").scrollIntoViewIfNeeded()
  await expect(page.locator(".int-chat .int-msg-agent .int-msg-text")).toHaveText(en.integrations.agent.answer)
  await expect(page.locator(".int-chat .int-msg-agent")).toBeVisible()
  expect(await page.locator(".int-chat .int-msg-agent").evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  expect(await page.locator(".int-beats i").last().evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  await context.close()
})

test("the footer ends with a call to action and an organized set of links", async ({ page }) => {
  await page.goto("/")
  const footer = page.locator("footer")
  await expect(footer.getByRole("link", { name: en.hero.primary })).toHaveAttribute("href", "#self-host")
  const star = footer.getByRole("link", { name: new RegExp(en.hero.secondary) })
  await expect(star).toHaveAttribute("href", REPO_URL)
  await expect(star).toHaveAttribute("target", "_blank")
  const links = footer.getByRole("navigation", { name: en.footer.label })
  const expected: [string, string][] = [
    [en.footer.github, REPO_URL],
    [en.footer.guide, GUIDE_URL],
    [en.footer.docs, DOCS_URL],
    [en.footer.changelog, CHANGELOG_URL],
    [en.footer.licenseLink, LICENSE_URL],
    [en.footer.trademarks, TRADEMARKS_URL],
  ]
  for (const [name, href] of expected) await expect(links.getByRole("link", { name, exact: true })).toHaveAttribute("href", href)
  await expect(links.getByRole("list", { name: en.footer.projectTitle }).getByRole("listitem")).toHaveCount(4)
  await expect(links.getByRole("list", { name: en.footer.legalTitle }).getByRole("listitem")).toHaveCount(2)
  await expect(footer.getByText(en.footer.noTrackers, { exact: true })).toBeVisible()
  await expect(footer.getByText(en.footer.noTrackersBody, { exact: true })).toBeVisible()
  await expect(footer).not.toContainText("network tab")
  // The sleeping ghost mumbles its five more minutes (and then falls quiet).
  await expect(footer.locator(".speech-bubble")).toHaveText([en.footer.sleepTalk])
})

for (const width of [1440, 390]) {
  test(`at ${width}px, the Overview's "All good!" bubble points at the ghost`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    await page.goto("/")
    const health = page.locator(".mock-health")
    await health.scrollIntoViewIfNeeded()
    const ghost = (await health.locator(".mock-health-ghost").boundingBox())!
    const bubble = (await health.locator(".mock-health-bubble").boundingBox())!
    // Under the ghost, centered on it, with its tail on the top edge pointing up.
    expect(bubble.y).toBeGreaterThanOrEqual(ghost.y + ghost.height - 1)
    expect(Math.abs(bubble.x + bubble.width / 2 - (ghost.x + ghost.width / 2))).toBeLessThan(2)
    const tail = await health.locator(".mock-health-bubble").evaluate((element) => {
      const style = getComputedStyle(element, "::before")
      return { top: parseFloat(style.top), transform: style.transform }
    })
    expect(tail.top).toBeLessThan(0)
    // rotate(135deg): the corner where its two borders meet points up.
    expect(tail.transform).toMatch(/^matrix\(-0\.70710\d*, 0\.70710\d*, -0\.70710\d*, -0\.70710\d*/)
    await context.close()
  })
}

for (const width of [1440, 390]) {
  test(`at ${width}px, the Activity mockup leads each event with its outcome and its sign, in Sam's week`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    await page.goto("/")
    const mock = page.locator(".mock-activity")
    await mock.scrollIntoViewIfNeeded()
    const rows = mock.locator(".mock-act")
    await expect(rows).toHaveCount(en.app.activity.rows.length)
    const marks = await rows.evaluateAll((all) => all.map((row) => row.getAttribute("data-mark")))
    expect(marks).toEqual(["added", "changed", "added", "removed", "skipped"])
    await expect(rows.first()).toContainText("Dentist")
    await expect(rows.first()).toContainText("Mon 15:00–16:30")
    const box = (await mock.boundingBox())!
    for (const [index, row] of (await rows.all()).entries()) {
      const copy = en.app.activity.rows[index]!
      await expect(row.locator(".mock-act-outcome")).toHaveText(copy.outcome)
      await expect(row.locator(".mock-act-sign svg")).toHaveCount(1)
      await expect(row.locator(".mock-act-rule img.avatar")).toHaveCount(2)
      const outcome = (await row.locator(".mock-act-outcome").boundingBox())!
      const event = (await row.locator(".mock-act-event").boundingBox())!
      expect(outcome.y + outcome.height).toBeLessThanOrEqual(event.y + 1)
      // Nothing spills out of the mockup, even on a phone.
      for (const part of await row.locator(":scope > *").all()) {
        const partBox = (await part.boundingBox())!
        expect(partBox.x + partBox.width).toBeLessThanOrEqual(box.x + box.width + 0.5)
      }
    }
    await context.close()
  })
}

test("the app is shown feature by feature, each with its mockup, on alternating sides", async ({ page }) => {
  await page.goto("/")
  const features = page.locator(".feat")
  const titles = [en.app.features.rules.title, en.app.features.activity.title, en.app.features.health.title]
  await expect(features.getByRole("heading", { level: 3 })).toHaveText(titles)
  const sides: boolean[] = []
  for (const feature of await features.all()) {
    await expect(feature.getByRole("img")).toHaveCount(1)
    const copy = (await feature.locator(".feat-copy").boundingBox())!
    const shot = (await feature.locator(".feat-shot").boundingBox())!
    sides.push(shot.x > copy.x)
  }
  expect(sides).toEqual([true, false, true])
})

test("the green ghost appears only where it means healthy", async ({ page }) => {
  await page.goto("/")
  const outside = await page
    .locator('.ghost[data-tone="moss"]')
    .evaluateAll((ghosts) => ghosts.filter((ghost) => !ghost.closest(".mock-health, .int-tile")).length)
  expect(outside).toBe(0)
  await expect(page.locator('.ghost[data-tone="mist"][data-glow]').first()).toBeAttached()
})

test("in the agent mockup, the AI assistant answers, not the ghost", async ({ page }) => {
  await page.goto("/")
  const chat = page.locator(".int-chat")
  await expect(chat.locator(".ghost")).toHaveCount(0)
  await expect(chat.locator(".int-agent-name")).toHaveText("Claude")
  // Claude's own mark, bundled inline in its orange.
  const mark = chat.locator(".int-agent-avatar svg.int-agent-mark")
  await expect(mark).toHaveCount(1)
  await expect(mark.locator("path")).toHaveAttribute("fill", "#D97757")
  await expect(chat).toContainText("calendar-ghost · get_status")
})

for (const width of [1440, 390]) {
  test(`at ${width}px: each How it works number sits on its title's line, the body under the title`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    await page.goto("/")
    const steps = page.locator(".how-steps li")
    await expect(steps).toHaveCount(3)
    for (const step of await steps.all()) {
      const number = (await step.locator(".how-step-n").boundingBox())!
      const title = (await step.locator("h3").boundingBox())!
      const body = (await step.locator("h3 + p").boundingBox())!
      expect(number.x + number.width).toBeLessThanOrEqual(title.x)
      // On the same line: the number overlaps the title's first line vertically.
      expect(number.y).toBeLessThan(title.y + title.height)
      expect(number.y + number.height).toBeGreaterThan(title.y)
      expect(body.y).toBeGreaterThanOrEqual(title.y + title.height - 1)
      expect(Math.abs(body.x - title.x)).toBeLessThanOrEqual(1)
    }
    await context.close()
  })
}

for (const width of [390, 660]) {
  test(`at ${width}px: How it works cards fit their content and stay centered`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    await page.goto("/")
    const steps = page.locator(".how-steps li")
    const cards = page.locator(".how-frag")
    await expect(cards).toHaveCount(3)
    for (const [index, card] of (await cards.all()).entries()) {
      const step = (await steps.nth(index).boundingBox())!
      const frame = (await card.boundingBox())!
      expect(frame.width).toBeLessThan(step.width * 0.8)
      expect(Math.abs(frame.x + frame.width / 2 - (step.x + step.width / 2))).toBeLessThanOrEqual(1)
    }
    await context.close()
  })
}

const bodyBackground = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor)

for (const path of ["/", "/docs/self-hosting", "/404"]) {
  test(`${path}: the theme toggle is there, 44px tall, and names the theme on screen`, async ({ browser }) => {
    for (const colorScheme of ["light", "dark"] as const) {
      const context = await browser.newContext({ colorScheme })
      const page = await context.newPage()
      await page.goto(path)
      const toggle = page.locator("[data-theme-toggle]")
      await expect(toggle).toBeVisible()
      expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      expect((await toggle.boundingBox())!.width).toBeGreaterThanOrEqual(44)
      // With nothing saved it follows the device, and says so.
      await expect(toggle).toHaveAttribute("data-choice", colorScheme)
      await expect(toggle).toHaveAttribute("aria-label", `Theme: ${en.theme[colorScheme]}`)
      await context.close()
    }
  })
}

for (const path of ["/", "/docs/self-hosting"]) {
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
    // Only the page's own two faces load.
    const families = await page.evaluate(() => [...document.fonts].map((font) => font.family.replaceAll('"', "")))
    expect(new Set(families)).toEqual(new Set(["Figtree Variable", "Besley Variable"]))
  })
}

test("the toggle switches between Light and Dark only: the first press saves the opposite of the device's theme", async ({ browser }) => {
  for (const colorScheme of ["light", "dark"] as const) {
    const context = await browser.newContext({ colorScheme })
    const page = await context.newPage()
    await page.goto("/")
    const toggle = page.locator("[data-theme-toggle]")
    const opposite = colorScheme === "light" ? "dark" : "light"
    await expect(page.locator("html")).not.toHaveAttribute("data-theme")
    const device = await bodyBackground(page)

    await toggle.click()
    await expect(toggle).toHaveAttribute("data-choice", opposite)
    await expect(toggle).toHaveAttribute("aria-label", `Theme: ${en.theme[opposite]}`)
    await expect(page.locator("html")).toHaveAttribute("data-theme", opposite)
    const switched = await bodyBackground(page)
    expect(switched).not.toBe(device)
    expect(await page.evaluate(() => localStorage.getItem("calendar-ghost-site-theme"))).toBe(opposite)

    await toggle.click()
    await expect(toggle).toHaveAttribute("data-choice", colorScheme)
    await expect(page.locator("html")).toHaveAttribute("data-theme", colorScheme)
    expect(await bodyBackground(page)).toBe(device)

    // Two states only: a third press is the opposite again, never a Device state.
    await toggle.click()
    await expect(toggle).toHaveAttribute("data-choice", opposite)
    await context.close()
  }
})

test("the theme choice survives a reload", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "light" })
  const page = await context.newPage()
  await page.goto("/")
  const toggle = page.locator("[data-theme-toggle]")
  await toggle.click() // Dark
  const before = await bodyBackground(page)
  await expect(toggle).toHaveAttribute("aria-label", `Theme: ${en.theme.dark}`)

  await page.reload()
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
  expect(await bodyBackground(page)).toBe(before)
  await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("data-choice", "dark")
  await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("aria-label", `Theme: ${en.theme.dark}`)
  await context.close()
})

test("with nothing saved, the page follows the emulated prefers-color-scheme, and an old Device choice counts as nothing saved", async ({ browser }) => {
  const backgrounds: string[] = []
  for (const colorScheme of ["dark", "light"] as const) {
    const context = await browser.newContext({ colorScheme })
    const page = await context.newPage()
    await page.goto("/")
    await page.evaluate(() => localStorage.setItem("calendar-ghost-site-theme", "device"))
    await page.reload()
    await expect(page.locator("[data-theme-toggle]")).toHaveAttribute("data-choice", colorScheme)
    await expect(page.locator("html")).not.toHaveAttribute("data-theme")
    backgrounds.push(await bodyBackground(page))
    await context.close()
  }
  expect(backgrounds[0]).not.toBe(backgrounds[1])
})

for (const page of DOC_PAGES) {
  test.describe(`/docs/${page.slug}, built from ${page.source}`, () => {
    test("renders the document with its contents, GitHub's anchors, and where to edit it", async ({ page: tab }) => {
      await tab.goto(docPagePath(page.slug))
      await expect(tab.locator(".doc h1")).toHaveCount(1)
      await expect(tab).toHaveTitle(/· Calendar Ghost$/)
      // Every contents entry lands on a heading of the document.
      const contents = tab.getByRole("navigation", { name: en.docs.contents })
      const targets = await contents.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href")))
      expect(targets.length).toBeGreaterThan(3)
      for (const href of targets.filter((target) => target?.startsWith("#"))) {
        await expect(tab.locator(`.doc :is(h2, h3)[id="${href!.slice(1)}"]`)).toHaveCount(1)
      }
      const note = tab.locator(".doc-source")
      await expect(note).toContainText(page.source)
      await expect(note.getByRole("link", { name: en.docs.edit })).toHaveAttribute("href", `${REPO_URL}/edit/main/${page.source}`)
      // Links to the other rendered document stay here; links to any other repository file go to GitHub.
      for (const href of await tab.locator(".doc a").evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""))) {
        expect(href, href).toMatch(/^(https?:|#|\/docs\/|mailto:)/)
        if (!href.startsWith("http")) expect(href, href).not.toMatch(/\.md(#|$)/)
        if (href.startsWith("/docs/")) expect(DOC_PAGES.map((doc) => docPagePath(doc.slug))).toContain(href.split("#")[0])
      }
    })

    test("each code block has a Copy button that copies exactly its code", async ({ page: tab }) => {
      await tab.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
      await tab.goto(docPagePath(page.slug))
      const blocks = tab.locator(".doc .doc-code")
      expect(await blocks.count()).toBeGreaterThan(0)
      expect(await blocks.count()).toBe(await tab.locator(".doc pre").count())
      const block = blocks.first()
      const button = block.locator("button")
      await expect(button).toHaveText(en.selfHost.copy)
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await button.click()
      const code = await block.locator("pre code").textContent()
      expect(await tab.evaluate(() => window.getSelection()?.toString())).toBe(code)
      await expect(button).toHaveText(en.selfHost.selected)
    })

    for (const colorScheme of ["light", "dark"] as const) {
      test(`in ${colorScheme}, highlighted code keeps 4.5:1 contrast`, async ({ browser }) => {
        const context = await browser.newContext({ colorScheme })
        const tab = await context.newPage()
        await tab.goto(docPagePath(page.slug))
        const worst = await tab.evaluate(() => {
          const canvas = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!
          const rgb = (color: string) => {
            canvas.clearRect(0, 0, 1, 1)
            canvas.fillStyle = color
            canvas.fillRect(0, 0, 1, 1)
            return Array.from(canvas.getImageData(0, 0, 1, 1).data.slice(0, 3))
          }
          const luminance = (channels: number[]) => {
            const [r, g, b] = channels.map((value) => {
              const c = value / 255
              return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
            })
            return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
          }
          let lowest = Infinity
          for (const pre of document.querySelectorAll(".doc pre")) {
            const background = luminance(rgb(getComputedStyle(pre).backgroundColor))
            for (const span of pre.querySelectorAll("span")) {
              if (!span.textContent?.trim()) continue
              const text = luminance(rgb(getComputedStyle(span).color))
              const [light, dark] = [Math.max(text, background), Math.min(text, background)]
              lowest = Math.min(lowest, (light + 0.05) / (dark + 0.05))
            }
          }
          return lowest
        })
        expect(worst).toBeGreaterThanOrEqual(4.5)
        await context.close()
      })
    }

    test("nothing scrolls sideways on a 320px screen, and nothing loads from another host", async ({ browser, baseURL }) => {
      const context = await browser.newContext({ viewport: { width: 320, height: 740 } })
      const tab = await context.newPage()
      const foreign: string[] = []
      tab.on("request", (request) => {
        if (new URL(request.url()).host !== new URL(baseURL!).host) foreign.push(request.url())
      })
      await tab.goto(docPagePath(page.slug))
      await tab.waitForLoadState("networkidle")
      expect(foreign).toEqual([])
      expect(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      // On a phone the contents fold into one control above the text.
      await expect(tab.locator(".doc-toc-narrow summary")).toBeVisible()
      await expect(tab.locator(".doc-toc-wide")).toBeHidden()
      await context.close()
    })
  })
}

test("the self-hosting guide keeps the deep link to monitors and agents, and links to troubleshooting on the site", async ({ page }) => {
  await page.goto(INTEGRATIONS_URL)
  await expect(page.locator('[id="6-connect-monitors-and-agents"]')).toBeInViewport()
  await expect(page.locator(".doc a[href='/docs/troubleshooting#a-monitor-or-agent-cannot-read-status']")).toHaveCount(1)
  await expect(page.locator(".doc a[href^='https://github.com/DannieBGoode/calendar-ghost/blob/main/docs/data-ownership.md']").first()).toBeAttached()
})

test("every link to the self-hosting guide on the home page opens the page rendered here", async ({ page }) => {
  await page.goto("/")
  const hrefs = await page.locator("a").evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""))
  expect(hrefs.filter((href) => href.includes("self-hosting.md"))).toEqual([])
  expect(hrefs).toContain(GUIDE_URL)
  expect(hrefs).toContain(INTEGRATIONS_URL)
})

test.describe("the Haunted Week", () => {
  const incoming = (page: Page) => page.locator(".haunt .hw-event.is-incoming")

  test("rests on its final state without JavaScript or with reduced motion: every plan Busy, Work's meetings as they are", async ({ browser }) => {
    for (const options of [{ javaScriptEnabled: false }, { reducedMotion: "reduce" as const }]) {
      const context = await browser.newContext(options)
      const page = await context.newPage()
      await page.goto("/")
      await page.locator(".haunt").scrollIntoViewIfNeeded()
      await expect(incoming(page)).toHaveCount(5)
      for (const event of await incoming(page).all()) {
        await expect(event).toHaveAttribute("data-state", "busy")
        await expect(event.locator(".hw-face.is-busy")).toHaveCSS("opacity", "1")
        await expect(event.locator(".hw-face.is-busy")).toContainText(en.demo.busy)
        await expect(event.locator(".hw-glyph")).toHaveCount(1)
        await expect(event.locator(".hw-dot")).toHaveCount(1)
      }
      await expect(page.locator(".haunt .hw-event.is-work")).toHaveCount(5)
      await expect(page.locator(".haunt .hw-event.is-work").first()).toContainText(en.demo.events.standup.title)
      await context.close()
    }
  })

  test("a plan arrives in transit, with its calendar's portrait and a dashed outline, then turns Busy", async ({ page }) => {
    await page.goto("/")
    await page.locator(".haunt").scrollIntoViewIfNeeded()
    const dentist = incoming(page).first()
    await expect(dentist).toHaveAttribute("data-state", "transit", { timeout: 4000 })
    await expect(dentist.locator(".hw-face.is-transit")).toContainText(en.demo.events.dentist.title)
    await expect(dentist.locator("img.avatar")).toHaveCount(1)
    await expect(dentist.locator(".hw-skin.is-transit")).toHaveCSS("border-top-style", "dashed")
    await expect.poll(() => dentist.evaluate((element) => Number(getComputedStyle(element).opacity))).toBeLessThan(1)
    // No "from Personal" line: the portrait says where it comes from.
    await expect(dentist).not.toContainText("from")
    await expect(dentist).toHaveAttribute("data-state", "busy", { timeout: 6000 })
    // The ghost is the actor: 64 to 80px.
    const ghost = (await page.locator(".haunt-ghost").boundingBox())!
    expect(ghost.width).toBeGreaterThanOrEqual(64)
    expect(ghost.width).toBeLessThanOrEqual(80)
  })

  for (const width of [320, 390, 1440]) {
    test(`at ${width}px the visible days fit the frame, with event text of at least 13px`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce" })
      const page = await context.newPage()
      await page.goto("/")
      const frame = page.locator(".haunt-frame")
      await frame.scrollIntoViewIfNeeded()
      const box = (await frame.boundingBox())!
      const days = page.locator(".haunt .hw-day:visible:not(.is-empty)")
      const expectedDays = width < 720 ? en.demo.days.slice(0, 3) : en.demo.days
      await expect(days).toHaveText(expectedDays)
      for (const day of await days.all()) {
        const dayBox = (await day.boundingBox())!
        expect(dayBox.x).toBeGreaterThanOrEqual(box.x)
        expect(dayBox.x + dayBox.width).toBeLessThanOrEqual(box.x + box.width + 0.5)
        expect(dayBox.y + dayBox.height).toBeLessThanOrEqual(box.y + box.height)
      }
      const events = page.locator(".haunt .hw-event:visible")
      await expect(events).toHaveCount(width < 720 ? 6 : 10)
      for (const event of await events.all()) {
        const eventBox = (await event.boundingBox())!
        expect(eventBox.x + eventBox.width).toBeLessThanOrEqual(box.x + box.width)
        expect(eventBox.y + eventBox.height).toBeLessThanOrEqual(box.y + box.height)
      }
      const sizes = await events.locator(".hw-title").evaluateAll((titles) => titles.map((title) => parseFloat(getComputedStyle(title).fontSize)))
      expect(Math.min(...sizes)).toBeGreaterThanOrEqual(13)
      await context.close()
    })
  }

  test("its pause control sits on the calendar's bar, says Pause and Play, and holds the loop", async ({ page }) => {
    await page.goto("/")
    await page.locator(".haunt").scrollIntoViewIfNeeded()
    const pause = page.locator(".haunt-bar").getByRole("button", { name: en.motion.pause, exact: true })
    await expect(pause).toHaveText(en.motion.pauseShort)
    expect((await pause.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await pause.click()
    const play = page.locator(".haunt-bar").getByRole("button", { name: en.motion.play, exact: true })
    await expect(play).toHaveText(en.motion.playShort)
    const states = () => incoming(page).evaluateAll((events) => events.map((event) => event.getAttribute("data-state")).join())
    const held = await states()
    await page.waitForTimeout(1200)
    expect(await states()).toBe(held)
  })
})

test("the night watch stands just above the cards, clear of them, and ticks in time with the monitor's newest check", async ({ browser }) => {
  for (const width of [1440, 1024, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    await page.goto("/")
    const watch = page.locator("#integrations .watch")
    await watch.scrollIntoViewIfNeeded()
    const box = (await watch.boundingBox())!
    const labels = page.locator("#integrations .int-reader h3")
    const firstLabel = (await labels.first().boundingBox())!
    // 24 to 32px above the cards' labels, overlapping no card and no label.
    const gap = firstLabel.y - (box.y + box.height)
    expect(gap, `${width}px: gap above the labels`).toBeGreaterThanOrEqual(24)
    expect(gap, `${width}px: gap above the labels`).toBeLessThanOrEqual(32)
    for (const item of await page.locator("#integrations .int-reader").all()) {
      const card = (await item.boundingBox())!
      expect(box.y + box.height <= card.y || box.x + box.width <= card.x || box.x >= card.x + card.width, `${width}px: clear of a card`).toBe(true)
    }
    const lead = (await page.locator("#integrations .int-lead").boundingBox())!
    if (width >= 900) {
      // In the heading row's right half, its feet on the line of the sentence's last line, over
      // the right two cards, clear of the sentence.
      expect(Math.abs(box.y + box.height - (lead.y + lead.height)), `${width}px: on the sentence's line`).toBeLessThan(4)
      const middle = (await page.locator("#integrations .int-mock").nth(1).boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(middle.x)
      const leadEnd = await page.locator("#integrations .int-lead").evaluate((lead) => {
        const range = document.createRange()
        range.selectNodeContents(lead)
        return Math.max(...[...range.getClientRects()].map((rect) => rect.right))
      })
      expect(box.x, `${width}px: clear of the sentence`).toBeGreaterThan(leadEnd)
    } else {
      // On a phone, its own row under the sentence, at the right.
      expect(box.y).toBeGreaterThanOrEqual(lead.y + lead.height)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
    }
    await context.close()
  }

  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto("/")
  await page.locator("#integrations .watch").scrollIntoViewIfNeeded()
  await expect(page.locator("#integrations .watch")).toHaveAttribute("data-awake", "")
  const timing = await page.evaluate(() => {
    const all = document.getAnimations() as CSSAnimation[]
    const pick = (name: string) => all.filter((animation) => animation.animationName.includes(name))
    const describe = (animation: Animation) => ({ start: Number(animation.startTime), end: Number(animation.effect?.getComputedTiming().endTime) })
    return { ticks: pick("watch-tick").map(describe), newest: pick("int-newest").map(describe) }
  })
  expect(timing.ticks).toHaveLength(3)
  expect(timing.newest).toHaveLength(1)
  // They start from the same change, and the newest check's last beat lands with the last tick.
  for (const tick of timing.ticks) expect(Math.abs(tick.start - timing.newest[0]!.start)).toBeLessThan(20)
  expect(timing.newest[0]!.end).toBe(Math.max(...timing.ticks.map((tick) => tick.end)))
  await context.close()
})

test("the homelab's night watch: one ghost by a rack, its checklist ticked when nothing moves", async ({ browser }) => {
  for (const options of [{ reducedMotion: "reduce" as const }, { javaScriptEnabled: false }]) {
    const context = await browser.newContext(options)
    const page = await context.newPage()
    await page.goto("/")
    const watch = page.locator("#integrations .watch")
    await expect(watch).toHaveAttribute("aria-hidden", "true")
    await expect(watch.locator(".ghost")).toHaveCount(1)
    await expect(page.locator("#integrations .ghost")).toHaveCount(2) // the night watch, and the dashboard tile's healthy ghost
    for (const tick of await watch.locator(".watch-tick").all()) await expect(tick).toHaveCSS("opacity", "1")
    expect(await watch.evaluate((element) => element.getAnimations({ subtree: true }).length)).toBe(0)
    await context.close()
  }
})
