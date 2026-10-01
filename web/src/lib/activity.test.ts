import { describe, expect, it } from "vitest"

import { ApiError } from "./api"
import {
  describeEntry,
  entryInspection,
  eventLookupFailure,
  changeListing,
  fieldChangeLines,
  fieldLabel,
  formatRunTime,
  groupRuns,
  whatHappened,
} from "./activity"
import { activityStateFromSearch } from "./activity-location"
import type { AuditEntry } from "./api"

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    run_id: "run-1",
    occurred_at: "2026-09-28T15:18:46+00:00",
    rule_id: "rule-1",
    action: "ignore",
    outcome: "skipped",
    category: "skipped",
    reason: "recurring_unsupported",
    detail: "",
    source_event_id: "source-event",
    destination_event_id: null,
    event: null,
    repeated: false,
    changed_fields: null,
    ...overrides,
  }
}

const names = { source: "Personal", destination: "Work" }

describe("activity presentation", () => {
  it("explains skipped recurring events in calendar language", () => {
    const copy = describeEntry(entry({}))
    expect(whatHappened(entry({}), names).text).toBe("Recurring event → skipped")
    expect(copy.explanation).toContain("Earlier versions")
  })

  it("names what was observed and in which calendar, then what Calendar Sync did", () => {
    const line = (reason: string, action = "update") =>
      whatHappened(entry({ action, reason, category: "changed" }), names).text

    expect(line("source_created", "create")).toBe("New in Personal → added to Work")
    expect(line("source_cancelled", "delete")).toBe("Cancelled in Personal → removed from Work")
    expect(line("occurrence_cancelled", "delete")).toBe("Cancelled in Personal → removed from Work")
    expect(line("projection_missing", "create")).toBe("Missing from Work → put back")
    expect(line("destination_drift_repaired")).toBe("Edited in Work → changed back to match Personal")
  })

  it("never claims who changed an event", () => {
    for (const reason of ["projection_missing", "destination_drift_repaired", "occurrence_drift_repaired"]) {
      const copy = describeEntry(entry({ reason }), names)
      expect(`${copy.trigger} ${copy.effect} ${copy.explanation}`).not.toMatch(/someone|somebody/i)
    }
  })

  it("says a write redoes the previous run's", () => {
    expect(
      whatHappened(entry({ action: "create", reason: "projection_missing", category: "changed", repeated: true }), names).text,
    ).toBe("Missing from Work → put back again")
  })

  it("says when a changed event moved, and from when", () => {
    const moved = whatHappened(
      entry({
        action: "update",
        reason: "source_changed",
        category: "changed",
        event: {
          title: "Dentist",
          all_day: false,
          starts: "2026-09-30T11:00:00",
          ends: "2026-09-30T12:00:00",
          recurring: false,
          cancelled: false,
          renamed_from: null,
          moved_from: { all_day: false, starts: "2026-09-30T10:00:00", ends: "2026-09-30T11:00:00" },
        },
      }),
      names,
    )
    expect(moved.trigger).toMatch(/^Moved from 10:00\sAM in Personal$/)
    expect(moved.effect).toBe("updated in Work")
  })

  it("says what a block means for the destination and who acts", () => {
    const blocked = entry({ action: "conflict", reason: "destination_occurrence_missing", category: "blocked" })
    expect(whatHappened(blocked, names)).toMatchObject({
      text: "Not found in the series in Work → blocked, Work left unchanged",
      tone: "blocked",
    })
    const copy = describeEntry(blocked, names)
    expect(copy.explanation).toContain("may be missing or out of date in Work")
    expect(copy.next).toContain("daily check")
    expect(describeEntry(entry({ action: "conflict", reason: "source_unverifiable" }), names).next).toContain("Settings")
    const unmapped = describeEntry(entry({ action: "conflict", reason: "projection_unmapped" }), names)
    expect(unmapped.effect).toBe("blocked, left in Work")
    expect(unmapped.next).toBe("If you don't want it in Work, delete it there yourself.")
    const unreadable = describeEntry(entry({ action: "conflict", reason: "source_unverifiable" }), names)
    expect(unreadable.explanation).not.toContain("edited")
    expect(describeEntry(entry({ action: "create", reason: "source_created" }), names).next).toBeUndefined()
  })

  it("falls back to the recorded detail for entries without a reason code", () => {
    const copy = describeEntry(entry({ reason: null, detail: "excluded event has no managed projection" }))
    expect(copy.effect).toBe("skipped")
    expect(copy.explanation).toBe("excluded event has no managed projection")
  })

  it("says what happened to rule management entries without calling them event changes", () => {
    const changed = (action: string) => whatHappened(entry({ action, reason: null, category: "changed" }), names)

    expect(changed("policy_changed")).toMatchObject({ text: "Rule settings changed", icon: "rule", tone: "change" })
    expect(changed("rule_removed")).toMatchObject({ text: "Rule removed", icon: "rule", tone: "change" })
    expect(changed("remove_projection")).toMatchObject({ text: "Rule removed → removed from Work", icon: "removed" })
    expect(changed("detach_projection")).toMatchObject({ text: "Rule removed → kept in Work, no longer synced", icon: "kept" })
    expect(whatHappened(entry({ action: "removal_conflict", reason: null, category: "blocked" }), names)).toMatchObject({
      text: "Not verifiably written by this rule → left in Work during Rule Removal",
      icon: "blocked",
      tone: "blocked",
    })
  })

  it("only looks up events for rules that still exist", () => {
    expect(entryInspection(entry({}), true)).toBe("event")
    expect(entryInspection(entry({ action: "detach_projection", reason: null }), false)).toBe("details")
    expect(entryInspection(entry({ action: "policy_changed", reason: null, source_event_id: null }), true)).toBe(
      "details",
    )
    expect(
      entryInspection(entry({ action: "create", reason: null, detail: "", source_event_id: null }), true),
    ).toBeNull()
  })

  it("explains why an event lookup failed", () => {
    expect(eventLookupFailure(new ApiError("gone", 410))).toBe(
      "This rule was removed, so its events can no longer be looked up.",
    )
    expect(eventLookupFailure(new ApiError("unavailable", 503))).toBe(
      "Google is not configured, so the event cannot be looked up.",
    )
    expect(eventLookupFailure(new ApiError("provider", 424))).toBe(
      "Google could not return this event right now. The account may need reauthorization in Settings.",
    )
  })

  it("reserves colour for blocked changes and names unknown calendars plainly", () => {
    expect(whatHappened(entry({ action: "conflict", category: "skipped" }), names)).toMatchObject({
      icon: "skipped",
      tone: "quiet",
    })
    expect(
      whatHappened(entry({ action: "update", reason: "destination_drift_repaired", category: "changed" }), null),
    ).toMatchObject({ text: "Edited in the destination calendar → changed back to match the source calendar", icon: "repaired" })
    expect(whatHappened(entry({ reason: "projection_current", category: "unchanged" }), names)).toMatchObject({
      text: "Already up to date",
      trigger: null,
      tone: "quiet",
    })
  })

  it("groups consecutive entries by run and keeps legacy entries together by minute", () => {
    const runs = groupRuns([
      entry({ id: 5, run_id: "run-2" }),
      entry({ id: 4, run_id: "run-2", action: "create", category: "changed" }),
      entry({ id: 3, run_id: null, occurred_at: "2026-09-27T09:00:10+00:00" }),
      entry({ id: 2, run_id: null, occurred_at: "2026-09-27T09:00:50+00:00" }),
      entry({ id: 1, run_id: null, occurred_at: "2026-09-27T09:00:50+00:00", rule_id: "rule-2" }),
    ])

    expect(runs.map((run) => run.entries.map((item) => item.id))).toEqual([[5, 4], [3, 2], [1]])
  })

  it("keeps one group per run when concurrent rules interleave their entries", () => {
    const runs = groupRuns([
      entry({ id: 4, run_id: "work-run", rule_id: "rule-1" }),
      entry({ id: 3, run_id: "home-run", rule_id: "rule-2" }),
      entry({ id: 2, run_id: "work-run", rule_id: "rule-1", action: "create", category: "changed" }),
      entry({ id: 1, run_id: "home-run", rule_id: "rule-2" }),
    ])

    expect(runs.map((run) => [run.key, run.entries.map((item) => item.id)])).toEqual([
      ["work-run", [4, 2]],
      ["home-run", [3, 1]],
    ])
  })

  it("explains that events Calendar Sync wrote are never synced again", () => {
    expect(describeEntry(entry({ reason: "managed_projection_source" })).explanation).toContain("never synced again")
  })

  it("explains series with no occurrence left to sync", () => {
    const skipped = entry({ reason: "series_without_occurrences" })
    expect(whatHappened(skipped, names).text).toBe("Every occurrence cancelled in Personal → skipped")
    expect(describeEntry(skipped).explanation).toContain("synced again if an occurrence comes back")
    const removed = entry({ action: "delete", reason: "series_without_occurrences_removed", category: "changed" })
    expect(whatHappened(removed, names).text).toBe("No occurrence left in Personal → removed from Work")
  })

  it("uses relative day names for recent runs", () => {
    const now = new Date(2026, 8, 28, 18, 0)
    expect(formatRunTime(new Date(2026, 8, 28, 15, 18).toISOString(), now)).toMatch(/^Today at /)
    expect(formatRunTime(new Date(2026, 8, 27, 15, 18).toISOString(), now)).toMatch(/^Yesterday at /)
  })
})

describe("source changes", () => {
  const recorded = {
    title: "Planning",
    all_day: false,
    starts: "2026-09-30T11:00:00+00:00",
    ends: "2026-09-30T12:00:00+00:00",
    recurring: false,
    cancelled: false,
    renamed_from: null,
    moved_from: { all_day: false, starts: "2026-09-30T10:00:00+00:00", ends: "2026-09-30T11:00:00+00:00" },
  }

  it("names the fields that changed before what Calendar Sync did", () => {
    const changed = entry({
      action: "update",
      reason: "source_changed",
      category: "changed",
      changed_fields: ["title", "description"],
    })

    expect(whatHappened(changed, names).text).toBe("Title and description changed in Personal → updated in Work")
  })

  it("says a change the rule does not show needed nothing in the destination", () => {
    const unchanged = entry({ reason: "projection_current", category: "unchanged", changed_fields: ["guests"] })

    expect(whatHappened(unchanged, names).text).toBe("Guests changed in Personal → already up to date")
    expect(describeEntry(unchanged, names).explanation).toBe(
      "The event changed in Personal, and Work already matched it, so nothing was written for this entry.",
    )
  })

  it("keeps saying where an event moved from when only its time changed", () => {
    const moved = entry({
      action: "update",
      reason: "source_changed",
      category: "changed",
      changed_fields: ["time"],
      event: recorded,
    })

    expect(whatHappened(moved, names).text).toMatch(/^Moved from .+ in Personal → updated in Work$/)
  })

  it("lists several fields in a sentence", () => {
    const changed = entry({
      action: "update",
      reason: "occurrence_changed",
      category: "changed",
      changed_fields: ["time", "location", "conferencing"],
      event: recorded,
    })

    expect(whatHappened(changed, names).text).toBe(
      "Time, location, and video call links changed in Personal → updated in Work",
    )
  })

  it("shows a changed field's values before and after, and what a list gained and lost", () => {
    const none = { before: null, after: null, before_time: null, after_time: null, added: [], removed: [] }

    expect(fieldChangeLines({ ...none, field: "description", before: "", after: "Dial in: 1234#" })).toMatchObject({
      label: "Description",
      before: "(empty)",
      after: "Dial in: 1234#",
      added: [],
      removed: [],
    })
    expect(fieldChangeLines({ ...none, field: "guests", added: ["cleo@example.com"], removed: ["ben@example.com"] })).toMatchObject({
      label: "Guests",
      before: null,
      after: null,
      added: ["cleo@example.com"],
      removed: ["ben@example.com"],
    })
    expect(fieldChangeLines({ ...none, field: "response", before: "tentative", after: "accepted" })).toMatchObject({
      label: "Your response",
      before: "Maybe",
      after: "Yes",
    })
    const moved = fieldChangeLines({
      ...none,
      field: "time",
      before_time: { all_day: true, starts: "2026-09-30", ends: "2026-10-01" },
      after_time: { all_day: true, starts: "2026-10-02", ends: "2026-10-03" },
    })
    expect(moved.before).toMatch(/all day$/)
    expect(moved.after).toMatch(/all day$/)
    expect(moved.before).not.toBe(moved.after)
  })

  it("still lists every changed field once its values are no longer available", () => {
    const listing = changeListing({
      fields: ["title", "description", "guests"],
      values_available: false,
      changes: [
        { field: "title", before: "Planning", after: "Kick-off", before_time: null, after_time: null, added: [], removed: [] },
      ],
    })

    expect(listing.map((line) => [line.label, line.unavailable])).toEqual([
      ["Title", false],
      ["Description", true],
      ["Guests", true],
    ])
  })

  it("labels every tracked field", () => {
    expect(["title", "time", "description", "location", "guests", "recurrence", "conferencing"].map(fieldLabel)).toEqual([
      "Title",
      "Time",
      "Description",
      "Location",
      "Guests",
      "Repeat pattern",
      "Video call links",
    ])
  })
})

describe("activity address", () => {
  it("reads links that name the outcome with the earlier category parameter", () => {
    expect(activityStateFromSearch("?rule=rule-7&category=blocked")).toEqual({ ruleId: "rule-7", show: "blocked", entryId: null, query: "" })
    expect(activityStateFromSearch("?category=everything").show).toBe("")
    expect(activityStateFromSearch("?show=skipped&category=blocked").show).toBe("skipped")
  })
})
