/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import { ApiError, type PlanSummary, type SyncInterval } from "@/lib/api"
import { leaveThen } from "@/lib/leave-guard"

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
  intervals?: SyncInterval[]
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

/**
 * Renders the editor, or renders it again with new props, keeping what was typed. Cancel leaves
 * the way the Plans tab's does, asking first while changes are not saved.
 */
function show({ plan, pending, error, enabled = true, others = [], intervals = ["instant", "5_minutes"] }: Props) {
  root ??= createRoot(container)
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <PlanEditor
          plan={plan}
          enabled={enabled}
          others={others}
          intervals={intervals}
          pending={pending}
          error={error}
          onSave={onSave}
          onCancel={() => leaveThen(onCancel)}
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

function labelOf(input: HTMLInputElement): string {
  return [...(input.labels ?? [])].map((label) => label.textContent).join(" ")
}

/** The limit field around a count's number, by the number's id. */
function limitField(id: string): HTMLFieldSetElement {
  const found = field(id).closest("fieldset")
  if (!found) throw new Error(`No limit field around ${id}`)
  return found
}

/** One option of a limit field: None, Up to, or No limit. */
function option(id: string, label: string): HTMLInputElement {
  const found = [...limitField(id).querySelectorAll<HTMLInputElement>("input[type='radio']")].find(
    (radio) => labelOf(radio) === label,
  )
  if (!found) throw new Error(`No option ${label} for ${id}`)
  return found
}

function options(id: string): string[] {
  return [...limitField(id).querySelectorAll<HTMLInputElement>("input[type='radio']")].map(labelOf)
}

/** The Sync speed radio for an interval. */
function speed(interval: SyncInterval): HTMLInputElement {
  const found = container.querySelector<HTMLInputElement>(`[role='radiogroup'] input[type='radio'][value='${interval}']`)
  if (!found) throw new Error(`No sync speed ${interval}`)
  return found
}

function speedGroup(): HTMLElement {
  return container.querySelector<HTMLElement>("[role='radiogroup']")!
}

/** The footer's question before leaving changes not saved, while it asks. */
function question(): HTMLElement | null {
  return container.querySelector<HTMLElement>(".plan-panel-question")
}

/** How many changes the footer says are not saved; empty while there are none. */
function changes(): string {
  return container.querySelector(".plan-panel-changes")?.textContent ?? ""
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
  it("asks for a name, never a key, and says where people see it", () => {
    edit(null)
    expect(container.querySelector("[id$='-key']")).toBeNull()
    expect([...container.querySelectorAll("label")].map((label) => label.textContent)).not.toContain("Key")
    expect(container.querySelector("label[for='plan-new-name']")?.textContent).toBe("Name")
    expect(description(field("plan-new-name"))).toEqual(["People see this name in Your plan."])

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
    expect(field("plan-family-name").value).toBe("Family")
    type(field("plan-family-name"), "Family Large")
    submit()
    expect(onSave.mock.calls[0]?.[0]).toStrictEqual({
      name: "Family Large",
      limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
    })
  })

  it.each([
    [
      "rules",
      "Maximum active rules",
      "Running rules count, and rules waiting for an account to be reauthorized. Paused rules and drafts don't.",
      { choices: ["No limit", "Up to"], unit: "rules" },
    ],
    [
      "accounts",
      "Maximum calendar accounts",
      "Every connected account counts, disconnected ones too. Reconnecting is never refused.",
      { choices: ["No limit", "Up to"], unit: "accounts" },
    ],
    ["tokens", "Maximum Integration Tokens", "Revoked tokens don't count.", { choices: ["None", "Up to", "No limit"], unit: "" }],
  ])("puts the %s limit under Limits for each person as one choice, saying what counts", (limit, legend, hint, { choices, unit }) => {
    edit()
    const limits = form().querySelector("fieldset.plan-limits")!
    expect(limits.querySelector("legend")?.textContent).toBe("Limits for each person")
    const own = limitField(`plan-family-${limit}`)
    expect(limits.contains(own)).toBe(true)
    expect(own.querySelector("legend")?.textContent).toBe(legend)
    expect(description(own)).toEqual([hint])
    expect(options(`plan-family-${limit}`)).toEqual(choices)
    expect(option(`plan-family-${limit}`, "Up to").checked).toBe(true)
    // The number is named by the limit and reads as a spin button, never a scroll-wheel number field.
    const amount = field(`plan-family-${limit}`)
    expect(amount.getAttribute("role")).toBe("spinbutton")
    expect(amount.type).toBe("text")
    expect(element(amount.getAttribute("aria-labelledby")!).textContent).toBe(legend)
    expect(amount.closest("[data-stepper]")?.nextElementSibling?.textContent ?? "").toBe(unit)
  })

  it("names the unit by the number typed", () => {
    edit()
    type(field("plan-family-rules"), "1")
    expect(field("plan-family-rules").closest("[data-stepper]")?.nextElementSibling?.textContent).toBe("rule")
    type(field("plan-family-accounts"), "1")
    expect(field("plan-family-accounts").closest("[data-stepper]")?.nextElementSibling?.textContent).toBe("account")
  })

  it("offers sync speed as radio cards with what each does, and says longer intervals come later", () => {
    edit()
    const group = speedGroup()
    expect(form().querySelector("fieldset.plan-limits")?.contains(group)).toBe(true)
    expect(element(group.getAttribute("aria-labelledby")!).textContent).toBe("Sync speed")
    expect(description(group)).toEqual([
      "How soon changes reach the other calendars.",
      "Longer intervals arrive in a later release.",
    ])
    expect([...group.querySelectorAll<HTMLInputElement>("input[type='radio']")].map((radio) => [labelOf(radio), description(radio)])).toEqual([
      [
        "Instant",
        ["Changes sync soon after the calendar provider reports them, with a check every 5 minutes as a backup."],
      ],
      ["Every 5 minutes", ["Calendars are checked for changes every 5 minutes."]],
    ])
    expect(speed("instant").checked).toBe(true)
  })

  it("keeps an interval a later release saved, beside the offered ones", () => {
    show({
      plan: { ...family, limits: { ...family.limits, sync_interval: "60_minutes" } },
      pending: false,
      error: null,
      intervals: ["instant", "5_minutes", "60_minutes"],
    })
    expect(labelOf(speed("60_minutes"))).toBe("Every hour")
    expect(description(speed("60_minutes"))).toEqual(["Calendars are checked for changes every hour."])
    expect(speed("60_minutes").checked).toBe(true)
  })

  it("keeps a limit's number while No limit is chosen, so choosing Up to again keeps it", () => {
    edit(null)
    expect(option("plan-new-rules", "No limit").checked).toBe(true)
    const amount = field("plan-new-rules")
    expect(amount.value).toBe("")
    expect(amount.tabIndex).toBe(-1)
    click(option("plan-new-rules", "Up to"))
    expect(amount.tabIndex).toBe(0)
    type(amount, "4")
    click(option("plan-new-rules", "No limit"))
    expect(field("plan-new-rules").value).toBe("4")
    expect(field("plan-new-rules").tabIndex).toBe(-1)
    type(field("plan-new-name"), "Small")
    submit()
    expect(onSave.mock.calls[0]?.[0]).toMatchObject({ limits: { rules: null } })
    click(option("plan-new-rules", "Up to"))
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

    click(option("plan-new-rules", "Up to"))
    const rulesReason = "Enter how many active rules, from 1 to 10,000, or choose No limit."
    expect(reason()).toEqual([rulesReason])
    for (const wrong of ["0", "10001"]) {
      type(field("plan-new-rules"), wrong)
      expect(reason()).toEqual([rulesReason])
    }
    type(field("plan-new-rules"), "3")
    expect(reason()).toEqual([])

    click(option("plan-new-accounts", "Up to"))
    expect(reason()).toEqual(["Enter how many calendar accounts, from 1 to 10,000, or choose No limit."])
    type(field("plan-new-accounts"), "1")
    click(option("plan-new-tokens", "Up to"))
    const tokensReason = "Enter how many Integration Tokens, from 1 to 10,000, or choose None or No limit."
    expect(reason()).toEqual([tokensReason])
    type(field("plan-new-tokens"), "0")
    expect(reason()).toEqual([tokensReason])
    click(option("plan-new-tokens", "None"))
    expect(reason()).toEqual([])
    click(speed("5_minutes"))

    submit()
    expect(onSave.mock.calls[0]?.[0]).toStrictEqual({
      name: "Small",
      limits: { rules: 3, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
    })
  })

  it("counts the changes not saved, and says nothing while there are none", () => {
    edit()
    expect(changes()).toBe("")
    type(field("plan-family-name"), "Family Large")
    expect(changes()).toBe("1 change not saved")
    type(field("plan-family-rules"), "2")
    expect(changes()).toBe("2 changes not saved")
    type(field("plan-family-rules"), "5")
    expect(changes()).toBe("1 change not saved")
    click(option("plan-family-accounts", "No limit"))
    expect(changes()).toBe("2 changes not saved")
    click(option("plan-family-accounts", "Up to"))
    expect(changes()).toBe("1 change not saved")
    type(field("plan-family-name"), " Family ")
    expect(changes()).toBe("")
    click(speed("5_minutes"))
    expect(changes()).toBe("1 change not saved")
    // Saved, the plan says what was typed, so nothing is left unsaved.
    show({ plan: { ...family, limits: { ...family.limits, sync_interval: "5_minutes" } }, pending: false, error: null })
    expect(changes()).toBe("")
  })

  it("asks before leaving changes not saved, and keeps them until they are discarded", () => {
    edit()
    type(field("plan-family-rules"), "2")
    type(field("plan-family-name"), "Family Large")
    act(() => field("plan-family-name").focus())
    click(button("Cancel"))
    expect(onCancel).not.toHaveBeenCalled()
    // The footer asks in place of Save and Cancel, with Keep editing focused.
    expect(question()?.textContent).toContain("Discard 2 changes?")
    expect(element(question()!.getAttribute("aria-labelledby")!).textContent).toBe("Discard 2 changes?")
    expect([...question()!.querySelectorAll("button")].map((choice) => choice.textContent)).toEqual(["Keep editing", "Discard"])
    expect(document.activeElement).toBe(button("Keep editing"))
    expect(container.querySelector("button[type='submit']")).toBeNull()

    // Keep editing keeps what was typed, and focus returns where it was.
    click(button("Keep editing"))
    expect(question()).toBeNull()
    expect(field("plan-family-name").value).toBe("Family Large")
    expect(changes()).toBe("2 changes not saved")
    expect(document.activeElement).toBe(field("plan-family-name"))

    // Escape answers Keep editing too.
    click(button("Cancel"))
    act(() => {
      button("Keep editing").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    })
    expect(question()).toBeNull()
    expect(onCancel).not.toHaveBeenCalled()

    click(button("Cancel"))
    click(button("Discard"))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(question()).toBeNull()
    expect(field("plan-family-name").value).toBe("Family")
    expect(changes()).toBe("")
  })

  it("names one change as one", () => {
    edit()
    click(speed("5_minutes"))
    click(button("Cancel"))
    expect(question()?.querySelector("p")?.textContent).toBe("Discard 1 change?")
  })

  it("leaves at once with nothing to lose", () => {
    edit()
    type(field("plan-family-name"), "Family Large")
    type(field("plan-family-name"), "Family")
    click(button("Cancel"))
    expect(question()).toBeNull()
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it("has the browser ask before the tab closes or reloads only while changes are not saved", () => {
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true })
      window.dispatchEvent(event)
      return event.defaultPrevented
    }
    edit()
    expect(unload()).toBe(false)
    type(field("plan-family-rules"), "2")
    expect(unload()).toBe(true)
    type(field("plan-family-rules"), "5")
    expect(unload()).toBe(false)
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
      option("plan-family-rules", "No limit"),
      speed("5_minutes"),
    ]
    for (const control of controls) {
      expect(control.disabled).toBe(false)
      expect(control.getAttribute("aria-disabled")).toBe("true")
    }
    expect(field("plan-family-name").readOnly).toBe(true)
    expect(field("plan-family-rules").readOnly).toBe(true)

    type(field("plan-family-name"), "Other")
    click(option("plan-family-rules", "No limit"))
    click(speed("5_minutes"))
    click(button("Cancel"))
    submit()
    expect(field("plan-family-name").value).toBe("Family")
    expect(option("plan-family-rules", "No limit").checked).toBe(false)
    expect(speed("instant").checked).toBe(true)
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
      () => field("plan-family-name"),
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    ],
    [refusal("invalid_plan", { reason: "interval" }), () => speed("instant"), "Choose one of the offered sync intervals."],
    [refusal("plan_name_taken", { name: "Free" }), () => field("plan-family-name"), "Another plan is named Free. Choose a different name."],
    [
      refusal("invalid_plan", { reason: "limit" }),
      () => field("plan-family-rules"),
      "Enter each limit as a whole number up to 10000, at least 1 for rules and calendar accounts, or choose No limit.",
    ],
  ])("moves focus to the field a refusal names, and shows why under it", (error, refusedField, reason) => {
    edit()
    act(() => button("Save plan").focus())
    refuse(error)

    const refused = refusedField()
    expect(document.activeElement).toBe(refused)
    const invalid = refused.closest("[role='radiogroup']") ?? refused
    expect(invalid.getAttribute("aria-invalid")).toBe("true")
    expect(description(invalid)).toContain(reason)
    const shown = [...form().querySelectorAll("[role='alert']")]
    expect(shown.map((alert) => alert.textContent)).toEqual([reason])
    expect(shown[0]?.closest(".plan-field")?.contains(refused)).toBe(true)
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
      expect(description(named)).toEqual(["People see this name in Your plan.", reason])
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
    click(option("plan-family-rules", "No limit"))
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
    ["rules", "2", "1 person on Family has more active rules than this. Their rules keep syncing, but they can't start another."],
    ["rules", "1", "3 people on Family have more active rules than this. Their rules keep syncing, but they can't start another."],
    ["accounts", "1", "2 people on Family have more calendar accounts than this. They keep them, but can't connect another."],
    ["tokens", "None", "2 people on Family have more Integration Tokens than this. They keep them, but can't issue another."],
    ["tokens", "1", "1 person on Family has more Integration Tokens than this. They keep them, but can't issue another."],
  ])("warns, and announces, how many people a lower %s limit of %s leaves with more", (limit, lower, warning) => {
    edit()
    const status = element(`plan-family-${limit}-warning`)
    expect(status.getAttribute("role")).toBe("status")
    expect(status.textContent).toBe("")

    if (lower === "None") click(option(`plan-family-${limit}`, "None"))
    else type(field(`plan-family-${limit}`), lower)
    expect(status.textContent).toBe(warning)
    expect(status.getAttribute("data-tone")).toBe("attention")
    expect(status.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(description(field(`plan-family-${limit}`))).toContain(warning)
    expect(limitField(`plan-family-${limit}`).contains(status)).toBe(true)

    click(option(`plan-family-${limit}`, "Up to"))
    type(field(`plan-family-${limit}`), "9")
    expect(status.textContent).toBe("")
  })

  it("does not warn when a lower limit leaves nobody with more than it allows", () => {
    edit({ ...family, use: { ...family.use, rules: [{ in_use: 2, people: 3 }] } })
    type(field("plan-family-rules"), "2")
    expect(element("plan-family-rules-warning").textContent).toBe("")
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "3 people on Family have more active rules than this. Their rules keep syncing, but they can't start another.",
    )
  })

  it("warns when a limit replaces No limit, naming one person as one", () => {
    edit({ ...family, limits: { ...family.limits, rules: null }, use: { ...family.use, rules: [{ in_use: 9, people: 1 }] } })
    click(option("plan-family-rules", "Up to"))
    type(field("plan-family-rules"), "8")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "1 person on Family has more active rules than this. Their rules keep syncing, but they can't start another.",
    )
  })

  it("says what a lower limit will do once plans are on, while they are off", () => {
    show({ plan: family, pending: false, error: null, enabled: false })
    type(field("plan-family-accounts"), "1")
    expect(element("plan-family-accounts-warning").textContent).toBe(
      "2 people on Family have more calendar accounts than this. Once plans are on, they keep them, but can't connect another.",
    )
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe(
      "3 people on Family have more active rules than this. Once plans are on, their rules keep syncing, but they can't start another.",
    )
    click(option("plan-family-tokens", "None"))
    expect(element("plan-family-tokens-warning").textContent).toBe(
      "2 people on Family have more Integration Tokens than this. Once plans are on, they keep them, but can't issue another.",
    )
  })

  it("does not warn for a plan that limits nobody, or a new plan", () => {
    edit({ ...family, limited_people: 0, use: { rules: [], connected_accounts: [], integration_tokens: [] } })
    type(field("plan-family-rules"), "1")
    expect(element("plan-family-rules-warning").textContent).toBe("")
    act(() => root?.unmount())
    root = null
    edit(null)
    click(option("plan-new-rules", "Up to"))
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
    click(option("plan-family-tokens", i18n.t("people.plans.editor.noLimit")))
    type(field("plan-family-rules"), "1")
    type(field("plan-family-accounts"), "1")
    refuse(refusal("invalid_plan", { reason: "name" }))
    expect(untranslatedText(container, [family.name])).toEqual([])
    act(() => root?.unmount())
    root = null
    show({ plan: family, pending: false, error: null, enabled: false })
    type(field("plan-family-rules"), "1")
    type(field("plan-family-accounts"), "1")
    click(option("plan-family-tokens", i18n.t("people.plans.editor.none")))
    expect(untranslatedText(container, [family.name])).toEqual([])
    act(() => root?.unmount())
    root = null
    show({ plan: null, pending: false, error: null, others: ["Free"] })
    click(option("plan-new-rules", i18n.t("people.plans.editor.upTo")))
    type(field("plan-new-name"), "Free")
    submit()
    expect(untranslatedText(container, ["Free"])).toEqual([])
    click(button(i18n.t("people.plans.editor.cancel")))
    expect(question()).not.toBeNull()
    expect(untranslatedText(container, ["Free"])).toEqual([])
  })
})
