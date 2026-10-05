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
  await expect(page.locator(".crossing-stage").getByText(en.demo.busy).first()).toBeVisible()
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
  ]
  for (const control of controls) {
    await expect(control.first()).toBeVisible()
    for (const item of await control.all()) expect((await item.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  }
  await context.close()
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
  const links = page.locator("#features a.doc-link")
  expect(await links.evaluateAll((all) => all.map((link) => link.getAttribute("href")))).toEqual([...TRUST_DOCS])
  for (const [index, link] of (await links.all()).entries()) {
    await expect(link).toContainText(en.trust.cards[index]!.title)
    await expect(link).toContainText(en.trust.docs)
  }
})

for (const path of ["/", "/bold"]) {
  test(`${path}: monitors and agents come after the trust list, with a status check to copy`, async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
    await page.goto(path)
    const ids = await page.locator("main > section").evaluateAll((sections) => sections.map((section) => section.id))
    expect(ids.indexOf("integrations")).toBe(ids.indexOf("features") + 1)
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
    })

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
