import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"
import { STATUS_CHECK_COMMAND } from "../src/content/integrations"
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

const split = (page: Page) =>
  page.locator(".reveal-frame").evaluate((frame) => getComputedStyle(frame).getPropertyValue("--split").trim())

test("loads nothing from another host", async ({ page, baseURL }) => {
  const foreign: string[] = []
  const host = new URL(baseURL!).host
  page.on("request", (request) => {
    if (new URL(request.url()).host !== host) foreign.push(request.url())
  })
  await page.goto("/")
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await page.waitForLoadState("networkidle")
  expect(foreign).toEqual([])
})

test("with reduced motion, the hero rests at 55% and nothing sweeps", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")
  await page.waitForTimeout(300)
  expect(await split(page)).toBe("55%")
  await page.waitForTimeout(1200)
  expect(await split(page)).toBe("55%")
})

test("the hero slider works from the keyboard and keeps its position", async ({ page }) => {
  await page.goto("/")
  const slider = page.getByRole("slider", { name: en.demo.sliderLabel })
  await slider.focus()
  for (let press = 0; press < 10; press += 1) await slider.press("ArrowLeft")
  const value = await slider.inputValue()
  await page.waitForTimeout(800)
  expect(await slider.inputValue()).toBe(value)
  expect(await split(page)).toBe(`${value}%`)
  await expect(slider).toHaveAttribute("aria-valuetext", `${value}% of the week shows your view`)
})

test("without JavaScript, the content and the hero's resting state are there", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.hero.title)
  await expect(page.getByText(en.demo.workSees).first()).toBeVisible()
  await expect(page.getByText(en.faq.items[0]!.q)).toBeVisible()
  await expect(page.getByRole("img", { name: en.app.overview.alt })).toBeVisible()
  expect(await split(page)).toBe("55%")
  await expect(page.locator('button[data-copy="self-host-command-0"]')).toBeHidden()
  await expect(page.locator(".crossing-stage .crossing-landed").getByText(en.demo.busy)).toBeVisible()
  await expect(page.locator(".crossing-stays").getByText(en.crossing.alwaysStays[0])).toBeVisible()
  // No CSS state gates the bubble without JavaScript: the ghost just says the resting line.
  await expect(page.locator(".crossing-says")).toHaveText(en.ghost.crossingBusy)
  await expect(page.locator("#how-it-works .how-preview-row").first()).toContainText(en.demo.busy)
  // Nothing loops without JavaScript, so there is nothing to pause.
  await expect(page.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
  await context.close()
})

test("pausing the hero stops its sweep, and play starts it again", async ({ page }) => {
  await page.goto("/")
  const pause = page.locator(".reveal").getByRole("button", { name: en.motion.pause })
  await pause.click()
  const paused = await split(page)
  await page.waitForTimeout(900)
  expect(await split(page)).toBe(paused)
  await page.locator(".reveal").getByRole("button", { name: en.motion.play }).click()
  await expect.poll(() => split(page), { timeout: 3000 }).not.toBe(paused)
})

test("every self-running demo has a pause control a finger can hit", async ({ page }) => {
  await page.goto("/")
  // The Haunted Week and the Crossing hydrate when they scroll into view.
  for (const demo of [".reveal", ".haunt", ".crossing"]) await page.locator(demo).scrollIntoViewIfNeeded()
  const buttons = page.getByRole("button", { name: en.motion.pause })
  await expect(buttons).toHaveCount(3)
  for (const button of await buttons.all()) {
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
})

test("with reduced motion, there is nothing to pause", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")
  await expect(page.locator(".reveal-frame")).toBeVisible()
  await expect(page.getByRole("button", { name: en.motion.pause })).toHaveCount(0)
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

test("the footer's dozing ghost mumbles in its sleep, over its head, and the five-minute line is plain text", async ({ browser }) => {
  for (const options of [{}, { reducedMotion: "reduce" as const }, { javaScriptEnabled: false }, { viewport: { width: 390, height: 844 } }]) {
    const context = await browser.newContext(options)
    const page = await context.newPage()
    await page.goto("/")
    const watch = page.locator(".footer-watch")
    await expect(watch.locator('.ghost[data-face="sleepy"]')).toHaveCount(1)
    await expect(watch.locator("p.footer-watch-note")).toHaveText(en.footer.watch)
    const bubble = watch.locator(".speech-bubble")
    await expect(bubble).toHaveText(en.footer.sleepTalk)
    await bubble.scrollIntoViewIfNeeded()
    // It comes once the ghost has dozed off (at once, still, without motion or JavaScript).
    await expect(bubble).toHaveCSS("opacity", "1", { timeout: 6000 })
    const box = (await bubble.boundingBox())!
    const ghost = (await watch.locator(".ghost").boundingBox())!
    expect(box.y + box.height).toBeLessThanOrEqual(ghost.y + ghost.height * 0.3)
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    await context.close()
  }
})

for (const path of ["/", "/bold"]) {
  test(`${path}: the How it works ghost first appears where its flight starts, so nothing jumps`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(path)
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
}

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
  const sleeper = page.locator('.footer .ghost[data-alive="brief"]')
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

test("on a phone, the pitch fits the first screen and the week shows Monday to Wednesday", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" })
  const page = await context.newPage()
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toBeInViewport()
  await expect(page.getByRole("link", { name: en.hero.primary }).first()).toBeInViewport()
  const frame = (await page.locator(".reveal-frame").boundingBox())!
  const thursday = (await page.locator(".reveal-work .week-days span").nth(3).boundingBox())!
  const wednesday = (await page.locator(".reveal-work .week-days span").nth(2).boundingBox())!
  expect(wednesday.x + wednesday.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
  expect(thursday.x).toBeGreaterThanOrEqual(frame.x + frame.width - 1)
  await context.close()
})

test("a copy button selects the command when the clipboard is unavailable", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
  await page.goto("/#self-host")
  await page.locator('button[data-copy="self-host-command-1"]').click()
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("cp .env.example .env")
  await expect(page.locator('button[data-copy="self-host-command-1"]')).toHaveText(en.selfHost.selected)
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

for (const path of ["/", "/bold", "/journey", "/home/hero-a"]) {
  test(`${path}: the nav's Features link lands on the app's features, and the trust list has its own anchor`, async ({ page }) => {
    await page.goto(path)
    const link = page.locator("nav .nav-wide").getByRole("link", { name: en.nav.features, exact: true })
    await expect(link).toHaveAttribute("href", `${path}#features`)
    await expect(page.locator("#features h2")).toHaveText(en.app.title)
    await expect(page.locator("#features .feat")).toHaveCount(3)
    await expect(page.locator("#trust h2")).toHaveText(en.trust.title)
  })
}

for (const path of ["/", "/bold"]) {
  test(`${path}: monitors and agents come after the trust list, with a status check to copy`, async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
    await page.goto(path)
    const ids = await page.locator("main > section").evaluateAll((sections) => sections.map((section) => section.id))
    expect(ids.indexOf("integrations")).toBe(ids.indexOf("trust") + 1)
    expect(ids.indexOf("self-host")).toBe(ids.indexOf("integrations") + 1)
    const section = page.locator("#integrations")
    await expect(section.getByRole("heading", { level: 2 })).toHaveText(en.integrations.title)
    await expect(section.getByRole("link", { name: en.integrations.guide })).toHaveAttribute("href", INTEGRATIONS_URL)
    const copy = section.locator('button[data-copy="integrations-status-check"]')
    await copy.click()
    expect(await page.evaluate(() => window.getSelection()?.toString())).toBe(STATUS_CHECK_COMMAND)
    await expect(copy).toHaveText(en.selfHost.selected)
  })
}

for (const path of ["/", "/bold"]) {
  test(`${path}: the How it works switch changes what step 3's preview shows`, async ({ page }) => {
    await page.goto(path)
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
}

for (const path of ["/", "/bold"]) {
  test(`${path}: the crossing runs once, then rests on a clearly visible Busy on Work`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(path)
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
    // A real fill and a solid edge, not a faint outline.
    const look = await landed.evaluate((element) => {
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

  for (const width of [1440, 1024, 390]) {
    for (const colorScheme of ["light", "dark"] as const) {
      test(`${path} at ${width}px ${colorScheme}: the crossing explains itself, with what stays behind on the Personal card`, async ({
        browser,
      }) => {
        const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce", colorScheme })
        const page = await context.newPage()
        await page.goto(path)
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
}

test("without JavaScript, the integrations mockups show their final state", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  await page.locator("#integrations").scrollIntoViewIfNeeded()
  await expect(page.locator(".int-chat .int-msg-agent")).toHaveText(en.integrations.agent.answer)
  await expect(page.locator(".int-chat .int-msg-agent")).toBeVisible()
  expect(await page.locator(".int-chat .int-reply").evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  expect(await page.locator(".int-beats i").last().evaluate((element) => getComputedStyle(element).opacity)).toBe("1")
  await context.close()
})

for (const path of ["/", "/bold", "/journey"]) {
  test.describe(`${path}, shared promises`, () => {
    test("the footer ends with a call to action and an organized set of links", async ({ page }) => {
      await page.goto(path)
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
      // The home page's sleeping ghost only mumbles its five more minutes; the other endings stay quiet.
      if (path === "/") await expect(footer.locator(".speech-bubble")).toHaveText([en.footer.sleepTalk])
      else await expect(footer.locator(".speech-bubble")).toHaveCount(0)
    })

    for (const width of [1440, 390]) {
      test(`at ${width}px, the Overview's "All good!" bubble points at the ghost`, async ({ browser }) => {
        const context = await browser.newContext({ viewport: { width, height: 900 } })
        const page = await context.newPage()
        await page.goto(path)
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
        await page.goto(path)
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
      await page.goto(path)
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
      await page.goto(path)
      const outside = await page.locator('.ghost[data-tone="moss"]').evaluateAll(
        (ghosts) =>
          // The home hero keeps its ghost until its own redesign.
          ghosts.filter((ghost) => !ghost.closest(".mock-health, .int-tile, .hero .reveal-handle")).length,
      )
      expect(outside).toBe(0)
      await expect(page.locator('.ghost[data-tone="mist"][data-glow]').first()).toBeAttached()
    })

    test("in the agent mockup, the AI assistant answers, not the ghost", async ({ page }) => {
      await page.goto(path)
      const chat = page.locator(".int-chat")
      await expect(chat.locator(".ghost")).toHaveCount(0)
      await expect(chat.locator(".int-agent-name")).toHaveText("Claude Code")
      await expect(chat).toContainText("calendar-ghost · get_status")
    })
  })
}

for (const path of ["/", "/bold"]) {
  for (const width of [1440, 390]) {
    test(`${path} at ${width}px: each How it works number sits on its title's line, the body under the title`, async ({ browser }) => {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      await page.goto(path)
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
}

const bodyBackground = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor)

for (const path of ["/", "/bold", "/journey", "/home/hero-a2", "/versions"]) {
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
