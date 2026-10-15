/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"

import { YourPlanLink } from "./your-plan-link"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function rendered(i18n = testI18n()): HTMLDivElement {
  const container = document.createElement("div")
  const root = createRoot(container)
  act(() =>
    root.render(
      <StaticI18nProvider i18n={i18n}>
        <YourPlanLink />
      </StaticI18nProvider>,
    ),
  )
  return container
}

describe("YourPlanLink", () => {
  it("opens Settings at Your plan", () => {
    const link = rendered().querySelector("a")
    expect(link?.textContent).toBe("See your plan")
    expect(link?.getAttribute("href")).toBe("/settings/account#your-plan")
  })

  it("has no untranslated text", () => {
    expect(untranslatedText(rendered(pseudoI18n()))).toEqual([])
  })
})
