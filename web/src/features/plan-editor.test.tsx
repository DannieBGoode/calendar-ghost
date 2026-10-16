/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import { ApiError, type PlanSummary } from "@/lib/api"

import { PlanEditor } from "./plan-editor"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
  over_people: 0,
  // Of the 3 people it limits: rules 5, 2, 2; calendar accounts 3, 3, 1; tokens 2, 1, none.
  use: {
    rules: [
      { in_use: 5, people: 1 },
      { in_use: 2, people: 2 },
    ],
    connected_accounts: [
      { in_use: 3, people: 2 },
      { in_use: 1, people: 1 },
    ],
    integration_tokens: [
      { in_use: 2, people: 1 },
      { in_use: 1, people: 1 },
    ],
  },
}

type Props = {
  plan: PlanSummary | null
  pending: boolean
  error: unknown
  enabled?: boolean
  /** The names of the other Plans. */
  others?: string[]
}

let container: HTMLDivElement
let root: Root | null = null
let onSave = vi.fn()
let onCancel = vi.fn()
let i18n: I18n = testI18n()

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  onSave = vi.fn()
  onCancel = vi.fn()
  i18n = testI18n()
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
})

/** Renders the editor, or renders it again with new props, keeping what was typed. */
function show({ plan, pending, error, enabled = true, others = [] }: Props) {
  root ??= createRoot(container)
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <PlanEditor
          plan={plan}
          enabled={enabled}
          others={others}
          intervals={["instant", "5_minutes"]}
          pending={pending}
          error={error}
          onSave={onSave}
          onCancel={onCancel}
        />
      </StaticI18nProvider>,
    )
  })
}

function edit(plan: PlanSummary | null = family) {
  show({ plan, pending: false, error: null })
}

function element(id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`#${id}`)
  if (!found) throw new Error(`No element ${id}`)
  return found
}

function field(id: string): HTMLInputElement {
  return element(id) as HTMLInputElement
}

function select(id: string): HTMLSelectElement {
  return element(id) as HTMLSelectElement
}

function button(name: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((candidate) => candidate.textContent.trim() === name)
  if (!found) throw new Error(`No button "${name}"`)
  return found
}

function form(): HTMLFormElement {
  const found = container.querySelector("form")
  if (!found) throw new Error("No form")
  return found
}

/** The text of the elements an element's aria-describedby names, in order. */
function description(target: Element): string[] {
  const ids = target.getAttribute("aria-describedby")?.split(" ").filter(Boolean) ?? []
  return ids.map((id) => element(id).textContent)
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

function click(target: HTMLElement) {
  act(() => target.click())
}

function choose(target: HTMLSelectElement, value: string) {
  act(() => {
    target.value = value
    target.dispatchEvent(new Event("change", { bubbles: true }))
  })
}

function submit() {
  act(() => {
    form().dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
  })
}

function refusal(code: string, params: Record<string, string | number> = {}): ApiError {
  return new ApiError("Refused", 422, "The server's English.", { code, params })
}

/** Saves, then answers the save with `error`, as the Plans tab does. */
function refuse(error: unknown, plan: PlanSummary | null = family) {
  submit()
  show({ plan, pending: true, error: null })
  show({ plan, pending: false, error })
}

describe("PlanEditor", () => {
  it("asks for a name, never a key, and starts there", () => {
    edit(null)
    expect(container.querySelector("[id$='-key']")).toBeNull()
    expect([...container.querySelectorAll("label")].map((label) => label.textContent)).not.toContain("Key")
    expect(document.activeElement).toBe(field("plan-new-name"))

    type(field("plan-new-name"), " Family Plus ")
    submit()
    expect(onSave).toHaveBeenCalledTimes(1)
    expect(onSave.mock.calls[0]?.[0]).toStrictEqual({
      name: "Family Plus",
      limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
    })
  })

  it("edits a plan without showing its key", () => {
    edit()
    expect(container.querySelector("[id$='-key']")).toBeNull()
    expect(container.textContent).not.toContain("family")
    expect(document.activeElement).toBe(field("plan-family-name"))
    type(field("plan-family-name"), "Family Large")
    submit()
    expect(onSave.mock.calls[0]?.[0]).toStrictEqual({
      name: "Family Large",
      limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
    })
  })

  it.each([
    ["rules", "Rules that can sync", "Paused rules and drafts don't count."],
    ["accounts", "Calendar accounts they can connect", "Disconnected accounts count. Reconnecting an account is never refused."],
    ["tokens", "Integration Tokens they can have", "Revoked tokens don't count."],
  ])("puts the %s limit under Limits for each person, saying what counts", (limit, label, hint) => {
    edit()
    const limits = form().querySelector("fieldset")
    expect(limits?.querySelector("legend")?.textContent).toBe("Limits for each person")
    const group = limits?.querySelector(`[role='group'][aria-labelledby='plan-family-${limit}-label']`)
    expect(element(`plan-family-${limit}-label`).textContent).toBe(label)
    expect(container.querySelector(`label[for='plan-family-${limit}']`)?.textContent).toBe(label)
    expect(group?.querySelector(`#plan-family-${limit}`)).toBe(field(`plan-family-${limit}`))
    expect(description(group!)).toEqual([hint])
    const noLimit = field(`plan-family-${limit}-unlimited`)
    expect(group?.contains(noLimit)).toBe(true)
    expect(container.querySelector(`label[for='plan-family-${limit}-unlimited']`)?.textContent).toBe("No limit")
  })

  it("puts how soon calendars sync with the limits, and says longer intervals come later", () => {
    edit()
    const interval = select("plan-family-interval")
    expect(form().querySelector("fieldset")?.contains(interval)).toBe(true)
    expect(container.querySelector("label[for='plan-family-interval']")?.textContent).toBe("How soon calendars sync")
    expect(description(interval)).toEqual(["Longer intervals arrive in a later release."])
  })

  it("shows a limit's number only while it has one", () => {
    edit(null)
    expect(container.querySelector("#plan-new-rules")).toBeNull()
    expect(field("plan-new-rules-unlimited").checked).toBe(true)
    click(field("plan-new-rules-unlimited"))
    expect(field("plan-new-rules").value).toBe("")
    type(field("plan-new-rules"), "4")
    click(field("plan-new-rules-unlimited"))
    expect(container.querySelector("#plan-new-rules")).toBeNull()
    click(field("plan-new-rules-unlimited"))
    expect(field("plan-new-rules").value).toBe("4")
  })

  it("says why Save is unavailable, and sends nothing until it is", () => {
    edit(null)
    const save = button("Save plan")
    const reason = () => (save.getAttribute("aria-disabled") === "true" ? description(save) : [])
    expect(save.disabled).toBe(false)
    expect(reason()).toEqual(["Enter a name to save this plan."])
    submit()
    expect(onSave).not.toHaveBeenCalled()

    type(field("plan-new-name"), "Small")
    expect(save.getAttribute("aria-disabled")).toBeNull()
    expect(save.getAttribute("aria-describedby")).toBeNull()

    click(field("plan-new-rules-unlimited"))
    const rulesReason = "Enter how many rules can sync, from 1 to 10,000, or choose No limit."
    expect(reason()).toEqual([rulesReason])
    for (const wrong of ["0", "2.5", "10001", "-1"]) {
      type(field("plan-new-rules"), wrong)
      expect(reason()).toEqual([rulesReason])
    }
    type(field("plan-new-rules"), "3")
    expect(reason()).toEqual([])

    click(field("plan-new-accounts-unlimited"))
    expect(reason()).toEqual(["Enter how many calendar accounts they can connect, from 1 to 10,000, or choose No limit."])
    type(field("plan-new-accounts"), "1")
    click(field("plan-new-tokens-unlimited"))
    expect(reason()).toEqual(["Enter how many Integration Tokens they can have, from 0 to 10,000, or choose No limit."])
    type(field("plan-new-tokens"), "0")
    expect(reason()).toEqual([])
    choose(select("plan-new-interval"), "5_minutes")

    submit()
    expect(onSave.mock.calls[0]?.[0]).toStrictEqual({
      name: "Small",
      limits: { rules: 3, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
    })
  })

  it("keeps every control focusable while it saves, and ignores them until it ends", () => {
    edit()
    const save = button("Save plan")
    act(() => save.focus())
    submit()
    expect(onSave).toHaveBeenCalledTimes(1)
    show({ plan: family, pending: true, error: null })

    expect(document.activeElement).toBe(save)
    const controls = [
      save,
      button("Cancel"),
      field("plan-family-name"),
      field("plan-family-rules"),
      field("plan-family-rules-unlimited"),
      select("plan-family-interval"),
    ]
    for (const control of controls) {
      expect(control.disabled).toBe(false)
      expect(control.getAttribute("aria-disabled")).toBe("true")
    }
    expect(field("plan-family-name").readOnly).toBe(true)
    expect(field("plan-family-rules").readOnly).toBe(true)

    type(field("plan-family-name"), "Other")
    click(field("plan-family-rules-unlimited"))
    choose(select("plan-family-interval"), "5_minutes")
    click(button("Cancel"))
    submit()
    expect(field("plan-family-name").value).toBe("Family")
    expect(field("plan-family-rules-unlimited").checked).toBe(false)
    expect(select("plan-family-interval").value).toBe("instant")
    expect(onCancel).not.toHaveBeenCalled()
    expect(onSave).toHaveBeenCalledTimes(1)

    show({ plan: family, pending: false, error: null })
    expect(save.getAttribute("aria-disabled")).toBeNull()
    click(button("Cancel"))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it.each([
    [
      refusal("invalid_plan", { reason: "name" }),
      "plan-family-name",
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    ],
    [refusal("invalid_plan", { reason: "interval" }), "plan-family-interval", "Choose one of the offered sync intervals."],
    [refusal("plan_name_taken", { name: "Free" }), "plan-family-name", "Another plan is named Free. Choose a different name."],
    [
      refusal("invalid_plan", { reason: "limit" }),
      "plan-family-rules",
      "Enter each limit as a whole number up to 10000, at least 1 for rules and calendar accounts, or choose No limit.",
    ],
  ])("moves focus to the field a refusal names, and shows why under it", (error, id, reason) => {
    edit()
    act(() => button("Save plan").focus())
    refuse(error)

    const refused = element(id)
    expect(document.activeElement).toBe(refused)
    expect(refused.getAttribute("aria-invalid")).toBe("true")
    expect(description(refused)).toContain(reason)
    const shown = [...form().querySelectorAll("[role='alert']")]
    expect(shown.map((alert) => alert.textContent)).toEqual([reason])
    expect(shown[0]?.closest(".field-stack")?.contains(refused)).toBe(true)
    expect(form().querySelectorAll("[aria-invalid='true']")).toHaveLength(1)
  })

  it.each([" free ", "FREE", "Ｆｒｅｅ"])(
    "refuses %j before sending it, since another plan reads as that name, under Name and with focus there",
    (name) => {
      show({ plan: null, pending: false, error: null, others: ["Family", "Free"] })
      type(field("plan-new-name"), name)
      act(() => button("Save plan").focus())
      submit()

      expect(onSave).not.toHaveBeenCalled()
      const named = field("plan-new-name")
      expect(document.activeElement).toBe(named)
      expect(named.getAttribute("aria-invalid")).toBe("true")
      const reason = "Another plan is named Free. Choose a different name."
      expect(description(named)).toEqual([reason])
      expect([...form().querySelectorAll("[role='alert']")].map((alert) => alert.textContent)).toEqual([reason])

      // Pressing Save again takes focus back to the name it waits for.
      act(() => button("Save plan").focus())
      submit()
      expect(document.activeElement).toBe(named)
      expect(onSave).not.toHaveBeenCalled()

      type(named, "Free 2")
      expect(named.getAttribute("aria-invalid")).toBeNull()
      expect(form().querySelector("[role='alert']")).toBeNull()
      submit()
      expect(onSave.mock.calls[0]?.[0]).toMatchObject({ name: "Free 2" })
    },
  )

  it("lets a plan keep its own name in another case", () => {
    show({ plan: family, pending: false, error: null, others: ["Free"] })
    type(field("plan-family-name"), "FAMILY")
    submit()
    expect(onSave.mock.calls[0]?.[0]).toMatchObject({ name: "FAMILY" })
    expect(form().querySelector("[role='alert']")).toBeNull()
  })

  it("names the first limit with a number when a limit is refused", () => {
    edit()
    click(field("plan-family-rules-unlimited"))
    refuse(refusal("invalid_plan", { reason: "limit" }))
    expect(document.activeElement).toBe(field("plan-family-accounts"))
    expect(field("plan-family-accounts").getAttribute("aria-invalid")).toBe("true")
  })

  it.each([
    [refusal("plan_not_found"), "This plan no longer exists. Reload to see the current plans."],
    [new TypeError("Failed to fetch"), "The browser could not reach Calendar Ghost."],
  ])("shows a refusal that names no field at the foot of the form", (error, reason) => {
    edit()
    act(() => button("Save plan").focus())
    refuse(error)
    expect([...form().querySelectorAll("[role='alert']")].map((alert) => alert.textContent)).toEqual([reason])
    expect(form().querySelector("[aria-invalid]")).toBeNull()
    expect(document.activeElement).toBe(button("Save plan"))
  })

  it("clears a refusal once its field changes, and keeps it while others do", () => {
    edit()
    refuse(refusal("invalid_plan", { reason: "name" }))
    type(field("plan-family-rules"), "4")
    expect(field("plan-family-name").getAttribute("aria-invalid")).toBe("true")
    expect(form().querySelector("[role='alert']")).not.toBeNull()
    type(field("plan-family-name"), "Family Large")
    expect(field("plan-family-name").getAttribute("aria-invalid")).toBeNull()
    expect(form().querySelector("[role='alert']")).toBeNull()
    expect(document.activeElement).toBe(field("plan-family-name"))
  })

  it.each([
    [
      "rules",
      "2",
      "1 person on this plan has more rules syncing than this. Their rules keep syncing, but they cannot start another.",
    ],
    [
      "rules",
      "1",
      "3 people on this plan have more rules syncing than this. Their rules keep syncing, but they cannot start another.",
    ],
    [
      "accounts",
      "1",
      "2 people on this plan have more calendar accounts than this. They keep them, but cannot connect another.",
    ],
    [
      "tokens",
      "0",
      "2 people on this plan have more Integration Tokens than this. They keep them, but cannot issue another.",
    ],
    [
      "tokens",
      "1",
      "1 person on this plan has more Integration Tokens than this. They keep them, but cannot issue another.",
    ],
  ])("warns, and announces, how many people a lower %s limit of %s leaves with more", (limit, lower, warning) => {
    edit()
    const status = element(`plan-family-${limit}-warning`)
    expect(status.getAttribute("role")).toBe("status")
    expect(status.textContent).toBe("")

    type(field(`plan-family-${limit}`), lower)
    expect(status.textContent).toBe(warning)
    expect(status.getAttribute("data-tone")).toBe("attention")
    expect(status.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(description(field(`plan-family-${limit}`))).toContain(warning)

    type(field(`plan-family-${limit}`), "9")
    expect(status.textContent).toBe("")
  })

  it("does not warn when a lower limit leaves nobody with more than it allows", () => {
    edit({ ...family, use: { ...family.use, rules: [{ in_use: 2, people: 3 }] } })
    type(field("plan-family-rules"), "2")
    expect(element("plan-family-rules-warning").textContent).toBe("")
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "3 people on this plan have more rules syncing than this. Their rules keep syncing, but they cannot start another.",
    )
  })

  it("warns when a limit replaces No limit, naming one person as one", () => {
    edit({ ...family, limits: { ...family.limits, rules: null }, use: { ...family.use, rules: [{ in_use: 9, people: 1 }] } })
    click(field("plan-family-rules-unlimited"))
    type(field("plan-family-rules"), "8")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "1 person on this plan has more rules syncing than this. Their rules keep syncing, but they cannot start another.",
    )
  })

  it("says what a lower limit will do once plans are on, while they are off", () => {
    show({ plan: family, pending: false, error: null, enabled: false })
    type(field("plan-family-accounts"), "1")
    expect(element("plan-family-accounts-warning").textContent).toBe(
      "2 people on this plan have more calendar accounts than this. Once plans are on, they keep them, but cannot connect another.",
    )
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "3 people on this plan have more rules syncing than this. Once plans are on, their rules keep syncing, but they cannot start another.",
    )
    type(field("plan-family-tokens"), "0")
    expect(element("plan-family-tokens-warning").textContent).toBe(
      "2 people on this plan have more Integration Tokens than this. Once plans are on, they keep them, but cannot issue another.",
    )
  })

  it("does not warn for a plan that limits nobody, or a new plan", () => {
    edit({ ...family, limited_people: 0, use: { rules: [], connected_accounts: [], integration_tokens: [] } })
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe("")
    act(() => root?.unmount())
    root = null
    edit(null)
    click(field("plan-new-rules-unlimited"))
    type(field("plan-new-rules"), "1")
    expect(element("plan-new-rules-warning").textContent).toBe("")
  })

  it("has no untranslated text", () => {
    i18n = pseudoI18n()
    edit(null)
    expect(untranslatedText(container)).toEqual([])
    act(() => root?.unmount())
    root = null
    edit()
    click(field("plan-family-tokens-unlimited"))
    type(field("plan-family-rules"), "1")
    type(field("plan-family-accounts"), "1")
    refuse(refusal("invalid_plan", { reason: "name" }))
    expect(untranslatedText(container, [family.name])).toEqual([])
    act(() => root?.unmount())
    root = null
    show({ plan: family, pending: false, error: null, enabled: false })
    type(field("plan-family-rules"), "1")
    type(field("plan-family-accounts"), "1")
    type(field("plan-family-tokens"), "0")
    expect(untranslatedText(container, [family.name])).toEqual([])
    act(() => root?.unmount())
    root = null
    show({ plan: null, pending: false, error: null, others: ["Free"] })
    type(field("plan-new-name"), "Free")
    submit()
    expect(untranslatedText(container, ["Free"])).toEqual([])
  })
})
