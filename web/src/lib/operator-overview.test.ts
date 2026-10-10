import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import type { ResourceUse, ServerProblem } from "./api"
import {
  AS_ADMINISTRATOR,
  calendarName,
  callsMeaning,
  nextStep,
  ownStepTarget,
  problemText,
  resourceFacts,
  verdictTone,
  VERDICTS,
} from "./operator-overview"

const i18n = testI18n()

const problem = (kind: ServerProblem["kind"], summary: string): ServerProblem => ({
  kind,
  rule_id: "rule-1",
  summary,
  since: null,
  message: null,
  cause: null,
  last_tried_at: null,
})

describe("verdictTone", () => {
  it("colors a verdict by how much it needs someone", () => {
    expect(VERDICTS.map((verdict) => [verdict, verdictTone(verdict)])).toEqual([
      ["stalled", "stopped"],
      ["stopped", "stopped"],
      ["review", "attention"],
      ["waiting", "attention"],
      ["paused", "neutral"],
      ["setup", "neutral"],
      ["healthy", "healthy"],
    ])
  })
})

describe("problemText", () => {
  it("names a problem no Incident explains by its kind, in the catalog's words", () => {
    expect(problemText(i18n, problem("stalled", "Scheduled synchronization stopped running"), 0)).toBe(
      "Scheduled synchronization stopped running",
    )
    expect(problemText(i18n, problem("stopped", "Stopped syncing"), 0)).toBe("Stopped syncing")
    expect(problemText(i18n, problem("overdue", "Not synced in over a day"), 0)).toBe("Not synced in over a day")
    expect(problemText(i18n, problem("blocked", "3 events couldn't be synced"), 3)).toBe(
      "3 events couldn't be synced",
    )
  })

  it("translates a problem an Incident explains from its message", () => {
    const lapsed: ServerProblem = {
      ...problem("stopped", "A calendar account needs reauthorization"),
      message: { code: "authorization_lapsed", params: { provider: "google" } },
    }

    expect(problemText(i18n, lapsed, 0)).toBe("A Google Calendar account needs reauthorization")
  })
})

describe("resourceFacts", () => {
  const quiet: ResourceUse = {
    rules: 1,
    connected_accounts: 2,
    activity_entries: 1,
    provider_calls: [],
    since: "2026-09-10",
  }

  it("counts what a User keeps here and the calls their rules made", () => {
    const busy: ResourceUse = {
      ...quiet,
      rules: 3,
      activity_entries: 1204,
      provider_calls: [{ provider: "google", calls: 1530, rate_limited: 2, failed: 1 }],
    }

    expect(resourceFacts(i18n, busy)).toEqual({
      kept: ["3 rules", "2 Google accounts", "1,204 Activity entries"],
      calls: ["Google Calendar: 1,530 calls, 2 refused for too many requests, 1 failed"],
    })
  })

  it("says when no rule called a calendar provider", () => {
    expect(resourceFacts(i18n, quiet)).toEqual({
      kept: ["1 rule", "2 Google accounts", "1 Activity entry"],
      calls: [],
    })
  })
})

describe("calendarName", () => {
  it("names a numbered calendar in the reader's language, and a named one by its name", () => {
    expect(calendarName(i18n, { calendar: "Calendar 2", provider: "google", number: 2 })).toBe("Calendar 2")
    expect(calendarName(i18n, { calendar: "Family", provider: "google", number: null })).toBe("Family")
  })

  it("keeps the server's label when an older server sends no number", () => {
    const older = { calendar: "Calendar 2", provider: "google" } as unknown as Parameters<typeof calendarName>[1]
    expect(calendarName(i18n, older)).toBe("Calendar 2")
  })

  it("adds the person's own name for a number, for their eyes only", () => {
    const names = new Map([[2, "Family"]])
    expect(calendarName(i18n, { calendar: "Calendar 2", provider: "google", number: 2 }, names)).toBe(
      "Calendar 2 (Family)",
    )
  })
})

describe("callsMeaning", () => {
  const google = (calls: number, rate_limited: number, failed: number) => ({ provider: "google", calls, rate_limited, failed })

  it("says in one line whether the calls look normal", () => {
    expect(callsMeaning(i18n, [google(1000, 0, 3)])).toBe("These calls look normal.")
    expect(callsMeaning(i18n, [google(1000, 12, 3)])).toBe(
      "Google asked Calendar Ghost to slow down a few times, and it tried again later.",
    )
    expect(callsMeaning(i18n, [google(1000, 0, 80)])).toBe(
      "Many calls failed. A Google account usually needs reauthorization, or Google is having trouble.",
    )
    expect(callsMeaning(i18n, [])).toBeNull()
  })
})

describe("nextStep", () => {
  const lapsed: ServerProblem = {
    ...problem("stopped", "A calendar account needs reauthorization"),
    message: { code: "authorization_lapsed", params: { provider: "google" } },
  }
  const robin = { name: "robin@example.test" }

  it("says who acts on each problem, and how", () => {
    // The person fixes their own problems; the administrator is offered nothing to do.
    expect(nextStep(i18n, lapsed, robin)).toBe("robin@example.test can fix this from their dashboard.")
    expect(nextStep(i18n, lapsed, "self")).toBe("Reauthorize your Google account in Settings, under Connections.")
    expect(nextStep(i18n, problem("stopped", "Stopped syncing"), robin)).toBe(
      "robin@example.test can fix this from their dashboard.",
    )
    expect(nextStep(i18n, problem("blocked", "2 events"), robin)).toBe("robin@example.test can fix this from their dashboard.")
    expect(nextStep(i18n, problem("overdue", "late"), robin)).toBe("robin@example.test can fix this from their dashboard.")
    expect(nextStep(i18n, problem("blocked", "2 events"), "self")).toBe("Activity explains what happened and what to do.")
    expect(nextStep(i18n, problem("waiting", "busy"), robin)).toBe("Nothing to do: Calendar Ghost retries by itself.")
    expect(nextStep(i18n, problem("stalled", "stopped running"), robin)).toBe(
      "Restart Calendar Ghost on the computer it runs on. Nobody's rules synchronize until it runs again.",
    )
  })
})

describe("nextStep by Cause", () => {
  const robin = { name: "robin@example.test" }
  const lapse = (cause: ServerProblem["cause"]): ServerProblem => ({
    ...problem("stopped", "A calendar account needs reauthorization"),
    message: { code: "authorization_lapsed", params: { provider: "google" } },
    cause,
  })
  const failed = (kind: ServerProblem["kind"], cause: ServerProblem["cause"]): ServerProblem => ({
    ...problem(kind, "failed"),
    cause,
  })

  it("tells the User an administrator's Cause is temporarily unavailable, naming neither it nor the administrator", () => {
    expect(nextStep(i18n, lapse("api_disabled"), "self")).toBe(
      "Temporarily unavailable. To try again, choose Check access on your Google account in Settings, under Connections.",
    )
    expect(nextStep(i18n, failed("waiting", "quota_exceeded"), "self")).toBe(
      "Temporarily unavailable. Calendar Ghost tries again by itself.",
    )
    expect(ownStepTarget(lapse("api_disabled"))).toBe("connections")
    expect(ownStepTarget(failed("waiting", "quota_exceeded"))).toBeNull()
  })

  it("tells an administrator the fix is theirs, wherever they read it", () => {
    expect(nextStep(i18n, lapse("oauth_client_invalid"), robin)).toBe(
      "You fix this as the administrator, in Google Cloud. robin@example.test has nothing to do.",
    )
    expect(nextStep(i18n, lapse("oauth_client_invalid"), AS_ADMINISTRATOR)).toBe(
      "You fix this as the administrator, in Google Cloud.",
    )
    expect(ownStepTarget(lapse("oauth_client_invalid"), AS_ADMINISTRATOR)).toBeNull()
  })

  it("gives the User one step of their own for their Cause", () => {
    expect(nextStep(i18n, lapse("access_revoked"), "self")).toBe(
      "Reauthorize your Google account in Settings, under Connections.",
    )
    expect(ownStepTarget(lapse("access_revoked"))).toBe("connections")
    for (const cause of ["calendar_forbidden", "calendar_not_found"] as const) {
      expect(nextStep(i18n, failed("stopped", cause), "self")).toBe(
        "Open the rule to choose another calendar, or remove the rule.",
      )
      expect(ownStepTarget(failed("stopped", cause))).toBe("rule")
    }
    for (const cause of ["rate_limited", "temporary"] as const) {
      expect(nextStep(i18n, failed("waiting", cause), "self")).toBe("Nothing to do: Calendar Ghost retries by itself.")
      expect(ownStepTarget(failed("waiting", cause))).toBeNull()
    }
    // Calendar Ghost does not know the fix, so the usual step is offered as trying again.
    expect(nextStep(i18n, failed("stopped", "unknown"), "self")).toBe("Open the rule and preview it again to restart it.")
  })

  it("tells an administrator the User fixes their own Cause, and offers them nothing to do", () => {
    expect(nextStep(i18n, lapse("access_revoked"), robin)).toBe("robin@example.test can fix this from their dashboard.")
    expect(nextStep(i18n, failed("stopped", "calendar_not_found"), robin)).toBe(
      "robin@example.test can fix this from their dashboard.",
    )
    expect(nextStep(i18n, failed("stopped", "unknown"), robin)).toBe(
      "robin@example.test can try again from their dashboard.",
    )
    expect(nextStep(i18n, failed("waiting", "rate_limited"), robin)).toBe("Nothing to do: Calendar Ghost retries by itself.")
  })
})
