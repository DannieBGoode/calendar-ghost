import { describe, expect, it } from "vitest"

import { endpointDraft, replacementReadiness } from "./rule-replacement"

const rule = {
  source: { connected_account_id: "a", calendar_id: "personal", calendar_name: null },
  destination: { connected_account_id: "b", calendar_id: "work", calendar_name: null },
}

describe("endpointDraft", () => {
  it("follows the rule for every field the administrator has not edited", () => {
    expect(endpointDraft(rule, {})).toEqual({
      sourceAccount: "a",
      sourceCalendar: "personal",
      destinationAccount: "b",
      destinationCalendar: "work",
    })
  })

  it("keeps an edit, including a cleared calendar, over the rule's value", () => {
    expect(endpointDraft(rule, { destinationAccount: "a", destinationCalendar: "" })).toEqual({
      sourceAccount: "a",
      sourceCalendar: "personal",
      destinationAccount: "a",
      destinationCalendar: "",
    })
  })
})

describe("replacementReadiness", () => {
  it("cannot replace a rule with the calendars it already uses", () => {
    expect(replacementReadiness(rule, endpointDraft(rule, {}))).toEqual({ sameEndpoint: false, canSubmit: false })
  })

  it("can replace a rule once one calendar changes", () => {
    const draft = endpointDraft(rule, { destinationCalendar: "team" })
    expect(replacementReadiness(rule, draft)).toEqual({ sameEndpoint: false, canSubmit: true })
  })

  it("rejects a destination that is the source calendar", () => {
    const draft = endpointDraft(rule, { destinationAccount: "a", destinationCalendar: "personal" })
    expect(replacementReadiness(rule, draft)).toEqual({ sameEndpoint: true, canSubmit: false })
  })

  it("waits until both calendars are chosen", () => {
    const draft = endpointDraft(rule, { sourceAccount: "b", sourceCalendar: "" })
    expect(replacementReadiness(rule, draft)).toEqual({ sameEndpoint: false, canSubmit: false })
  })

  it("treats the same calendar id in another account as a different calendar", () => {
    const draft = endpointDraft(rule, { destinationCalendar: "personal" })
    expect(replacementReadiness(rule, draft)).toEqual({ sameEndpoint: false, canSubmit: true })
  })
})
