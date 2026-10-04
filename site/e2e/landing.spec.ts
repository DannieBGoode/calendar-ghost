import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"

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
