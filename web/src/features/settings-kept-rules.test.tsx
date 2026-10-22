/* @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import { api, ApiError, type OwnPlan, type RuleSummary } from "@/lib/api"
import { KeptRulesForm } from "./settings-kept-rules"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const plan: OwnPlan = {
  basis: "plan", plan: { key: "small", name: "Small", on_default: true },
  limits: { rules: 2, connected_accounts: 2, integration_tokens: 1, sync_interval: "instant" },
  rules_counted: 2, held_rules: 1, grace: null,
  rules: [{ rule_id: "a", place: "counted", kept: true }, { rule_id: "b", place: "reserved", kept: false }, { rule_id: "c", place: "held", kept: true }],
  connected_accounts: 2, integration_tokens: 0, instant: true, poll_every_minutes: 5,
  may_connect_account: false, may_issue_token: true, over_rule_limit: false,
}
function summary(id: string): RuleSummary {
  const endpoint = { connected_account_id: "account", calendar_id: id, calendar_name: id.toUpperCase() }
  return { id, source: endpoint, destination: { ...endpoint, calendar_name: "Work" }, state: "enabled", keeps_place: false, privacy_policy: "busy_only", stop_cause: null, sync_all_day_events: true, sync_birthdays: false, tentative_events: "mark", unanswered_invitations: "as_tentative", effective_cadence: "instant", poll_every_minutes: 5, last_sync: null, latest_preview: null, running: null, reprojection_required: false }
}
let root: Root | undefined
let container: HTMLDivElement
let client: QueryClient
async function settle() {
  for (let i = 0; i < 6; i += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
}
async function render(i18n: I18n = testI18n()) {
  vi.spyOn(api, "accounts").mockResolvedValue([])
  vi.spyOn(api, "rules").mockResolvedValue([summary("a"), summary("b"), summary("c")])
  vi.spyOn(api, "ownPlan").mockResolvedValue(plan)
  vi.spyOn(api, "chooseKeptRules").mockResolvedValue(undefined)
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root?.render(<StaticI18nProvider i18n={i18n}><QueryClientProvider client={client}><KeptRulesForm plan={plan} /></QueryClientProvider></StaticI18nProvider>))
  await settle()
}
function button(text: string) {
  const found = [...container.querySelectorAll("button")].find((item) => item.textContent === text)
  if (!found) throw new Error(`Missing button ${text}`)
  return found
}
async function click(element: HTMLElement) {
  act(() => { element.focus(); element.click() })
  await settle()
}
function boxes() { return [...container.querySelectorAll<HTMLInputElement>("input[type=checkbox]")] }
afterEach(() => {
  act(() => root?.unmount())
  container.remove()
  client.clear()
  vi.restoreAllMocks()
})

describe("KeptRulesForm", () => {
  it("test_keep_form_saves_whole_set_and_allows_unchanged_resave", async () => {
    await render()
    expect(boxes()).toHaveLength(0)
    await click(button("Choose which rules sync"))
    expect(boxes().map((box) => box.checked)).toEqual([true, false, true])
    expect(container.textContent).toContain("Active rule")
    expect(container.textContent).toContain("Reserved place")
    expect(container.textContent).toContain("Held by your plan")
    expect(container.textContent).toContain("2 selected, 2 maximum")
    expect([...container.querySelectorAll("label")].filter((label) => label.textContent.includes("Saved choice"))).toHaveLength(2)
    await click(boxes()[1]!)
    expect(boxes()[1]?.checked).toBe(false)
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["a", "c"])
    expect(container.textContent).toContain("Your choices were saved.")
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenCalledTimes(2)
    await click(boxes()[0]!)
    await click(boxes()[2]!)
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith([])
  })
  it("distinguishes duplicate calendar names by their connected accounts", async () => {
    await render()
    const rules = ["a", "b", "c"].map((id) => ({
      ...summary(id),
      source: { ...summary(id).source, calendar_name: "Calendar", connected_account_id: `source-${id}` },
      destination: { ...summary(id).destination, calendar_name: "Calendar", connected_account_id: `destination-${id}` },
    }))
    vi.mocked(api.accounts).mockResolvedValue(["a", "b", "c"].flatMap((id) => [
      { id: `source-${id}`, display_name: `Source ${id}`, email: `${id}@source.example`, provider: "google", state: "connected", authorization_lapsed_at: null, authorized_at: null, avatar_url: null, rule_count: 1 },
      { id: `destination-${id}`, display_name: `Destination ${id}`, email: `${id}@destination.example`, provider: "google", state: "connected", authorization_lapsed_at: null, authorized_at: null, avatar_url: null, rule_count: 1 },
    ]))
    await act(async () => { await client.invalidateQueries({ queryKey: ["accounts"] }) })
    vi.mocked(api.rules).mockResolvedValue(rules)
    await act(async () => { await client.invalidateQueries({ queryKey: ["rules"] }) })
    await click(button("Choose which rules sync"))
    for (const [index, box] of boxes().entries()) {
      const id = rules[index]!.id
      expect(box.labels?.[0]?.textContent).toContain(`Source ${id}`)
      expect(box.labels?.[0]?.textContent).toContain(`${id}@source.example`)
      expect(box.labels?.[0]?.textContent).toContain(`Destination ${id}`)
      expect(box.labels?.[0]?.textContent).toContain(`${id}@destination.example`)
    }
    await click(boxes()[0]!)
    await click(boxes()[2]!)
    const intended = boxes().find((box) => box.labels?.[0]?.textContent.includes("b@source.example"))!
    await click(intended)
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["b"])
  })
  it("falls back to account identifiers when their names cannot load", async () => {
    await render()
    vi.mocked(api.accounts).mockRejectedValue(new Error("unavailable"))
    await act(async () => { await client.invalidateQueries({ queryKey: ["accounts"] }) })
    await click(button("Choose which rules sync"))
    expect(boxes()[0]?.labels?.[0]?.textContent).toContain("From account to account")
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["a", "c"])
  })
  it("explicitly reviews selections excluded by refreshed standings and capacity", async () => {
    await render()
    await click(button("Choose which rules sync"))
    await click(boxes()[0]!)
    await click(boxes()[1]!)
    vi.mocked(api.ownPlan).mockResolvedValue({ ...plan, limits: { ...plan.limits!, rules: 1 }, rules: plan.rules.filter((rule) => rule.rule_id !== "c") })
    await act(async () => { await client.invalidateQueries({ queryKey: ["own-plan"] }) })
    await settle()
    expect(container.textContent).toContain("2 selected, 1 maximum")
    expect(boxes().map((box) => box.checked)).toEqual([false, true])
    expect(button("Save choices").getAttribute("aria-disabled")).toBe("true")
    await click(button("Review updated choices"))
    expect(container.textContent).toContain("1 selected, 1 maximum")
    expect(boxes().map((box) => box.checked)).toEqual([false, true])
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["b"])
  })
  it("explains that clearing preferences ranks future places without promising a switch", async () => {
    await render()
    await click(button("Choose which rules sync"))
    expect(container.textContent).toContain("Choose none to clear preferences for future free places and grace periods.")
    expect(container.textContent).toContain("This does not switch rules already syncing.")
  })
  it("allows whole-set resaves after only a secondary status refresh fails", async () => {
    await render()
    const observer = client.getQueryCache().build(client, { queryKey: ["dashboard"], queryFn: () => Promise.reject(new Error("unavailable")) })
    const invalidate = vi.spyOn(client, "invalidateQueries")
    invalidate.mockImplementation(async (filters, options) => {
      if (filters?.queryKey?.[0] === "dashboard") { await observer.fetch(); return }
      return QueryClient.prototype.invalidateQueries.call(client, filters, options)
    })
    await click(button("Choose which rules sync"))
    await click(button("Save choices"))
    expect(container.textContent).toContain("Your choices were saved.")
    expect(container.textContent).toContain("Some status views could not refresh. Refresh status to try again.")
    expect(button("Save choices").getAttribute("aria-disabled")).toBe("false")
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenCalledTimes(2)
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["a", "c"])
  })
  it.each([new ApiError("busy", 409, "busy", { code: "plan_settlement_busy" }), new ApiError("failed", 500)])("preserves edits and focus after a refused save ($status)", async (error) => {
    await render()
    vi.mocked(api.chooseKeptRules).mockRejectedValueOnce(error)
    await click(button("Choose which rules sync"))
    await click(boxes()[0]!)
    await click(boxes()[1]!)
    const save = button("Save choices")
    await click(save)
    expect(document.activeElement).toBe(save)
    expect(boxes().map((box) => box.checked)).toEqual([false, true, true])
    expect(container.querySelector("[role=alert]")).not.toBeNull()
    expect(api.chooseKeptRules).toHaveBeenCalledOnce()
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["b", "c"])
  })
  it("recovers stale choices through an explicit review before another save", async () => {
    await render()
    vi.mocked(api.chooseKeptRules).mockRejectedValueOnce(new ApiError("missing", 404))
    await click(button("Choose which rules sync"))
    vi.mocked(api.ownPlan).mockResolvedValue({ ...plan, rules: plan.rules.filter((rule) => rule.rule_id !== "c") })
    vi.mocked(api.rules).mockResolvedValue([summary("a"), summary("b")])
    await click(button("Save choices"))
    expect(api.ownPlan).toHaveBeenCalled()
    expect(api.rules).toHaveBeenCalledTimes(2)
    expect(button("Save choices").getAttribute("aria-disabled")).toBe("true")
    await click(button("Review updated choices"))
    await click(button("Save choices"))
    expect(api.chooseKeptRules).toHaveBeenCalledTimes(2)
    expect(api.chooseKeptRules).toHaveBeenLastCalledWith(["a"])
  })
  it("refreshes capacity after too-many and renders the coded message", async () => {
    await render()
    vi.mocked(api.chooseKeptRules).mockRejectedValueOnce(new ApiError("too many", 422, "too many", { code: "too_many_kept_rules", params: { count: 1 } }))
    await click(button("Choose which rules sync"))
    vi.mocked(api.ownPlan).mockResolvedValue({ ...plan, limits: { ...plan.limits!, rules: 1 } })
    await click(button("Save choices"))
    expect(container.textContent).toContain("Your plan lets you keep 1 rule.")
    expect(api.ownPlan).toHaveBeenCalled()
    expect(container.textContent).toContain("2 selected, 1 maximum")
    expect(button("Save choices").getAttribute("aria-disabled")).toBe("true")
  })
  it("acknowledges a committed save separately from refresh failure and retries only the read", async () => {
    await render()
    await click(button("Choose which rules sync"))
    vi.mocked(api.ownPlan).mockRejectedValue(new Error("unavailable"))
    await click(button("Save choices"))
    expect(container.textContent).toContain("Your choices were saved.")
    expect(container.textContent).toContain("Some status views could not refresh.")
    await click(button("Refresh status"))
    expect(api.chooseKeptRules).toHaveBeenCalledOnce()
  })
  it("never saves a partial list when an eligible rule has no readable name", async () => {
    await render()
    vi.mocked(api.rules).mockResolvedValue([summary("a")])
    await act(async () => { await client.invalidateQueries({ queryKey: ["rules"] }) })
    await click(button("Choose which rules sync"))
    expect(container.textContent).toContain("Rule names could not load.")
    expect(boxes()).toHaveLength(0)
    expect([...container.querySelectorAll("button")].some((item) => item.textContent === "Save choices")).toBe(false)
    await click(button("Try again"))
    expect(api.chooseKeptRules).not.toHaveBeenCalled()
  })
  it("has native labels, a pending state and a live result without dropping focus", async () => {
    await render()
    await click(button("Choose which rules sync"))
    for (const box of boxes()) {
      expect(box.labels?.length).toBe(1)
      expect(box.labels?.[0]?.textContent).toContain("Work")
    }
    let finish: (() => void) | undefined
    vi.mocked(api.chooseKeptRules).mockImplementation(() => new Promise<void>((resolve) => { finish = resolve }))
    const save = button("Save choices")
    await click(save)
    expect(container.querySelector("form")?.getAttribute("aria-busy")).toBe("true")
    expect(save.disabled).toBe(false)
    expect(document.activeElement).toBe(save)
    expect(boxes().every((box) => box.getAttribute("aria-disabled") === "true")).toBe(true)
    act(() => finish?.())
    await settle()
    expect(document.activeElement).toBe(save)
    expect(container.querySelector("[role=status]")?.textContent).toContain("Your choices were saved.")
    await click(button("Cancel"))
    expect(document.activeElement).toBe(button("Choose which rules sync"))
  })
  it("refreshes authoritative plans, rules and existing status query families after success", async () => {
    await render()
    const keys = [["rule", "a"], ["rule", "c"], ["dashboard"], ["people", "overview", "self"], ["people", "overview", "other"], ["installation-health"]]
    for (const key of keys) client.setQueryData(key, {})
    await click(button("Choose which rules sync"))
    await click(button("Save choices"))
    for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    expect(api.ownPlan).toHaveBeenCalledTimes(2)
    expect(api.rules).toHaveBeenCalledTimes(2)
  })
  it("preserves save focus even when the rule-name refresh fails", async () => {
    await render()
    await click(button("Choose which rules sync"))
    vi.mocked(api.rules).mockRejectedValue(new Error("unavailable"))
    const save = button("Save choices")
    await click(save)
    expect(document.activeElement).toBe(save)
    expect(container.textContent).toContain("Your choices were saved.")
    expect(boxes().map((box) => box.checked)).toEqual([true, false, true])
    expect(save.getAttribute("aria-disabled")).toBe("true")
  })
  it("has no raw keys or placeholders in the pseudo-locale", async () => {
    const i18n = pseudoI18n()
    await render(i18n)
    await click(button(i18n.t("settings.ownPlan.keep.open")))
    expect(untranslatedText(container, ["A", "B", "C", "Work", "account"])).toEqual([])
  })
})
