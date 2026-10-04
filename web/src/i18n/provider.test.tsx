/* @vitest-environment happy-dom */
import { act } from "react"
import { createRoot } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { LocaleEntry } from "./locales"
import english from "./locales/en"
import { I18nProvider, useI18n } from "./provider"
import type { Catalog } from "./types"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const german = { common: { time: { justNow: "gerade eben" } } } as unknown as Catalog
const locales: [LocaleEntry, ...LocaleEntry[]] = [
  { tag: "en", load: () => Promise.resolve(english) },
  { tag: "de", load: () => Promise.resolve(german) },
]

function Probe() {
  const { t } = useI18n()
  return <p>{t("common.time.justNow")}</p>
}

async function render(entries: LocaleEntry[]) {
  const container = document.createElement("div")
  document.body.append(container)
  const root = createRoot(container)
  // A thenable callback makes act wait for the catalog to load before it returns.
  await act(() => {
    root.render(<I18nProvider locales={entries}><Probe /></I18nProvider>)
    return Promise.resolve()
  })
  return { container, root }
}

afterEach(() => {
  localStorage.clear()
  document.body.innerHTML = ""
  vi.restoreAllMocks()
})

describe("I18nProvider", () => {
  it("renders English and sets the document language", async () => {
    const { container } = await render(locales)
    expect(container.textContent).toBe("just now")
    expect(document.documentElement.lang).toBe("en")
  })

  it("shows the saved language", async () => {
    localStorage.setItem("calendar-sync-locale", "de")
    const { container } = await render(locales)
    expect(container.textContent).toBe("gerade eben")
    expect(document.documentElement.lang).toBe("de")
  })

  it("shows English when a catalog fails to load", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined)
    localStorage.setItem("calendar-sync-locale", "de")
    const broken: LocaleEntry[] = [locales[0], { tag: "de", load: () => Promise.reject(new Error("chunk 404")) }]
    const { container } = await render(broken)
    expect(container.textContent).toBe("just now")
    expect(document.documentElement.lang).toBe("en")
  })

  it("uses navigator.language when navigator.languages is empty", async () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue([])
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE")
    const { container } = await render(locales)
    expect(container.textContent).toBe("gerade eben")
    expect(document.documentElement.lang).toBe("de")
  })

  it("announces the loading state with the product name", async () => {
    localStorage.setItem("calendar-sync-locale", "de")
    const pending: LocaleEntry[] = [locales[0], { tag: "de", load: () => new Promise<Catalog>(() => undefined) }]
    const { container } = await render(pending)
    const status = container.querySelector('[role="status"]')
    expect(status?.getAttribute("aria-label")).toBe("Calendar Ghost")
    expect(status?.getAttribute("aria-busy")).toBe("true")
  })
})
