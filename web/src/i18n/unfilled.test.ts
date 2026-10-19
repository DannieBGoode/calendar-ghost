/* @vitest-environment happy-dom */

import { describe, expect, it } from "vitest"

import { unfilledText, watchUnfilledText } from "./unfilled"

describe("unfilledText", () => {
  it("finds a placeholder the translator did not fill", () => {
    expect(unfilledText("{count} administrators")).toEqual(["{count}"])
    expect(unfilledText("Give {name} to {Provider}")).toEqual(["{name}", "{Provider}"])
  })

  it("finds a catalog key shown in place of its message, known or not", () => {
    expect(unfilledText("Never limited: people.plans.status.administrators")).toEqual(["people.plans.status.administrators"])
    expect(unfilledText("common.apiError.something_new")).toEqual(["common.apiError.something_new"])
  })

  it("leaves addresses, hosts, versions, other tools' variables, and JSON alone", () => {
    const text =
      'robin@example.test syncs calendar.google.com with v0.2.0. Bearer ${CALENDAR_GHOST_TOKEN} Bearer {{HOMEPAGE_VAR_TOKEN}} {"url": "https://example.test/mcp"} rules.example.test'
    expect(unfilledText(text)).toEqual([])
  })

  it("leaves alone words named after what every object has, such as constructor.name", () => {
    expect(unfilledText("constructor.name and people.toString")).toEqual([])
  })
})

/** A page of its own, so what these tests show never reaches the document the setup watches. */
function detachedPage(): HTMLElement {
  return document.createElement("main")
}

describe("watchUnfilledText", () => {
  it("reports text and labels shown at any moment, even once they are gone", async () => {
    const root = detachedPage()
    const watch = watchUnfilledText(root)
    const fact = document.createElement("p")
    fact.textContent = "{count} administrators"
    root.append(fact)
    const action = document.createElement("button")
    action.setAttribute("aria-label", "Remove {name}")
    root.append(action)
    await Promise.resolve()
    fact.remove()
    action.remove()
    expect(watch.stop()).toEqual(["{count} administrators", "Remove {name}"])
  })

  it("reports text that changes into a placeholder, and a key in a title", () => {
    const root = detachedPage()
    const fact = document.createElement("p")
    fact.textContent = "1 administrator"
    root.append(fact)
    const watch = watchUnfilledText(root)
    fact.firstChild!.nodeValue = "{count} administrators"
    root.setAttribute("title", "people.plans.status.neverLimited")
    expect(watch.stop()).toEqual(["{count} administrators", "people.plans.status.neverLimited"])
  })

  it("reports what the page holds when it stops, though it never changed", () => {
    const root = detachedPage()
    root.textContent = "{count} administrators"
    expect(watchUnfilledText(root).stop()).toEqual(["{count} administrators"])
  })

  it("reports nothing for a page whose words were all filled", async () => {
    const root = detachedPage()
    const watch = watchUnfilledText(root)
    const fact = document.createElement("p")
    fact.textContent = "1 administrator"
    fact.setAttribute("aria-label", "Never limited: 1 administrator")
    root.append(fact)
    await Promise.resolve()
    expect(watch.stop()).toEqual([])
  })
})
