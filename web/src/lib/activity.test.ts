import { describe, expect, it } from "vitest"

import english from "@/i18n/locales/en"
import { pseudoize } from "@/i18n/pseudo"
import { pseudoI18n, testI18n } from "@/i18n/testing"
import { createI18n } from "@/i18n/translator"
import type { Catalog } from "@/i18n/types"

import { ApiError } from "./api"
import {
  changeMark,
  describeEntry,
  entryInspection,
  eventLookupFailure,
  changeListing,
  fieldChangeLines,
  fieldLabel,
  formatEventTime,
  formatRunTime,
  groupRuns,
  whatHappened,
} from "./activity"
import { activityStateFromSearch } from "./activity-location"
import type { AuditEntry } from "./api"

const i18n = testI18n()

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
    const copy = describeEntry(i18n, entry({}))
    expect(whatHappened(i18n, entry({}), names).text).toBe("Recurring event → skipped")
    expect(copy.explanation).toContain("Earlier versions")
  })

  it("names what was observed and in which calendar, then what Calendar Ghost did", () => {
    const line = (reason: string, action = "update") =>
      whatHappened(i18n, entry({ action, reason, category: "changed" }), names).text

    expect(line("source_created", "create")).toBe("New in Personal → added to Work")
    expect(line("source_cancelled", "delete")).toBe("Cancelled in Personal → removed from Work")
    expect(line("occurrence_cancelled", "delete")).toBe("Cancelled in Personal → removed from Work")
    expect(line("projection_missing", "create")).toBe("Missing from Work → put back")
    expect(line("destination_drift_repaired")).toBe("Edited in Work → changed back to match Personal")
  })

  it("never claims who changed an event", () => {
    for (const reason of ["projection_missing", "destination_drift_repaired", "occurrence_drift_repaired"]) {
      const copy = describeEntry(i18n, entry({ reason }), names)
      expect(`${copy.trigger} ${copy.effect} ${copy.explanation}`).not.toMatch(/someone|somebody/i)
    }
  })

  it("says a write redoes the previous run's", () => {
    expect(
      whatHappened(i18n, entry({ action: "create", reason: "projection_missing", category: "changed", repeated: true }), names).text,
    ).toBe("Missing from Work → put back again")
  })

  it("says when a changed event moved, and from when", () => {
    const moved = whatHappened(i18n,
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
    expect(whatHappened(i18n, blocked, names)).toMatchObject({
      text: "Not found in the series in Work → blocked, Work left unchanged",
      tone: "blocked",
    })
    const copy = describeEntry(i18n, blocked, names)
    expect(copy.explanation).toContain("may be missing or out of date in Work")
    expect(copy.next).toContain("daily check")
    expect(describeEntry(i18n, entry({ action: "conflict", reason: "source_unverifiable" }), names).next).toContain("Settings")
    const unmapped = describeEntry(i18n, entry({ action: "conflict", reason: "projection_unmapped" }), names)
    expect(unmapped.effect).toBe("blocked, left in Work")
    expect(unmapped.next).toBe("If you don't want it in Work, delete it there yourself.")
    const unreadable = describeEntry(i18n, entry({ action: "conflict", reason: "source_unverifiable" }), names)
    expect(unreadable.explanation).not.toContain("edited")
    expect(describeEntry(i18n, entry({ action: "create", reason: "source_created" }), names).next).toBeUndefined()
  })

  it("points to the recorded detail for entries without a reason code", () => {
    const copy = describeEntry(i18n, entry({ reason: null, detail: "excluded event has no managed projection" }))
    expect(copy.effect).toBe("skipped")
    expect(copy.explanation).toBe(
      "This version of Calendar Ghost cannot describe this entry yet. Its recorded detail is below.",
    )
  })

  it("never shows raw server text as the explanation of an unknown reason", () => {
    const copy = describeEntry(testI18n(), { reason: "brand_new_reason", action: "brand_new_action", detail: "internal: raw" })
    expect(copy.explanation).toBe("This version of Calendar Ghost cannot describe this entry yet. Its recorded detail is below.")
    expect(copy.effect).toBe("Something happened")
  })

  it("explains nothing for an unknown entry that recorded no detail", () => {
    expect(describeEntry(i18n, entry({ action: "create", reason: null, detail: "" })).explanation).toBe("")
  })

  it("says what happened to rule management entries without calling them event changes", () => {
    const changed = (action: string) => whatHappened(i18n, entry({ action, reason: null, category: "changed" }), names)

    expect(changed("policy_changed")).toMatchObject({ text: "Rule settings changed", icon: "rule", tone: "change" })
    expect(changed("rule_removed")).toMatchObject({ text: "Rule removed", icon: "rule", tone: "change" })
    expect(changed("remove_projection")).toMatchObject({ text: "Rule removed → removed from Work", icon: "removed" })
    expect(changed("detach_projection")).toMatchObject({ text: "Rule removed → kept in Work, no longer synced", icon: "kept" })
    expect(whatHappened(i18n, entry({ action: "removal_conflict", reason: null, category: "blocked" }), names)).toMatchObject({
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
    expect(eventLookupFailure(i18n, new ApiError("gone", 410))).toBe(
      "This rule was removed, so its events can no longer be looked up.",
    )
    expect(eventLookupFailure(i18n, new ApiError("unavailable", 503))).toBe(
      "Its calendar provider is not configured, so the event cannot be looked up.",
    )
    expect(eventLookupFailure(i18n, new ApiError("provider", 424))).toBe(
      "Its calendar provider could not return this event right now. The account may need reauthorization in Settings.",
    )
  })

  it("reserves colour for blocked changes and names unknown calendars plainly", () => {
    expect(whatHappened(i18n, entry({ action: "conflict", category: "skipped" }), names)).toMatchObject({
      icon: "skipped",
      tone: "quiet",
    })
    expect(
      whatHappened(i18n, entry({ action: "update", reason: "destination_drift_repaired", category: "changed" }), null),
    ).toMatchObject({ text: "Edited in the destination calendar → changed back to match the source calendar", icon: "repaired" })
    expect(whatHappened(i18n, entry({ reason: "projection_current", category: "unchanged" }), names)).toMatchObject({
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

  it("explains that events Calendar Ghost wrote are never synced again", () => {
    expect(describeEntry(i18n, entry({ reason: "managed_projection_source" })).explanation).toContain("never synced again")
  })

  it("explains series with no occurrence left to sync", () => {
    const skipped = entry({ reason: "series_without_occurrences" })
    expect(whatHappened(i18n, skipped, names).text).toBe("Every occurrence cancelled in Personal → skipped")
    expect(describeEntry(i18n, skipped).explanation).toContain("synced again if an occurrence comes back")
    const removed = entry({ action: "delete", reason: "series_without_occurrences_removed", category: "changed" })
    expect(whatHappened(i18n, removed, names).text).toBe("No occurrence left in Personal → removed from Work")
  })

  it("uses relative day names for recent runs", () => {
    const now = new Date(2026, 8, 28, 18, 0)
    expect(formatRunTime(i18n, new Date(2026, 8, 28, 15, 18).toISOString(), now)).toMatch(/^Today at /)
    expect(formatRunTime(i18n, new Date(2026, 8, 27, 15, 18).toISOString(), now)).toMatch(/^Yesterday at /)
  })
})

describe("event time ranges", () => {
  // Pinned against the code before Activity was translated; ICU may use a narrow no-break space.
  const now = new Date(2026, 8, 28, 12, 0)
  const at = (month: number, day: number, hour: number, minute = 0) => new Date(2026, month, day, hour, minute).toISOString()
  const range = (event: { all_day: boolean; starts: string; ends: string }, from = now) =>
    formatEventTime(i18n, event, from).replace(/\s/g, " ")

  it("names the day once for a timed event within one day", () => {
    expect(range({ all_day: false, starts: at(8, 30, 10), ends: at(8, 30, 11, 30) })).toBe("Wed, Sep 30, 10:00 AM – 11:30 AM")
  })

  it("names both days for a timed event across midnight", () => {
    expect(range({ all_day: false, starts: at(8, 30, 22), ends: at(9, 1, 1) })).toBe("Wed, Sep 30, 10:00 PM – Thu, Oct 1, 1:00 AM")
  })

  it("says all day for a single all-day event", () => {
    expect(range({ all_day: true, starts: "2026-09-30", ends: "2026-10-01" })).toBe("Wed, Sep 30, all day")
  })

  it("names the first and last day of a multi-day all-day event", () => {
    expect(range({ all_day: true, starts: "2026-09-30", ends: "2026-10-03" })).toBe("Wed, Sep 30 – Fri, Oct 2, all day")
  })

  it("adds the year for an event in another year", () => {
    const nextYear = { all_day: false, starts: new Date(2027, 0, 4, 10).toISOString(), ends: new Date(2027, 0, 4, 11).toISOString() }
    expect(range(nextYear)).toBe("Mon, Jan 4, 2027, 10:00 AM – 11:00 AM")
    expect(range({ all_day: true, starts: "2027-01-04", ends: "2027-01-06" })).toBe("Mon, Jan 4, 2027 – Tue, Jan 5, 2027, all day")
  })

  it("is empty when the event has no recorded time", () => {
    expect(formatEventTime(i18n, { all_day: false, starts: null, ends: null }, now)).toBe("")
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

  it("names the fields that changed before what Calendar Ghost did", () => {
    const changed = entry({
      action: "update",
      reason: "source_changed",
      category: "changed",
      changed_fields: ["title", "description"],
    })

    expect(whatHappened(i18n, changed, names).text).toBe("Title and description changed in Personal → updated in Work")
    const pseudo = whatHappened(pseudoI18n(), changed, names).text
    expect(pseudo).toContain(pseudoize("Title"))
    expect(pseudo).toContain(pseudoize("description"))
  })

  it("keeps a translator's capitalization for fields after the first", () => {
    const german = {
      ...english,
      activity: {
        ...english.activity,
        field: { ...english.activity.field, title: "Titel", description: "Beschreibung" },
        fieldInSentence: { ...english.activity.field, title: "Titel", description: "Beschreibung" },
      },
    } as unknown as Catalog
    const changed = entry({
      action: "update",
      reason: "source_changed",
      category: "changed",
      changed_fields: ["title", "description"],
    })

    expect(whatHappened(createI18n({ locale: "de", catalog: german }), changed, names).text).toMatch(/^Titel und Beschreibung /)
  })

  it("says a change the rule does not show needed nothing in the destination", () => {
    const unchanged = entry({ reason: "projection_current", category: "unchanged", changed_fields: ["guests"] })

    expect(whatHappened(i18n, unchanged, names).text).toBe("Guests changed in Personal → already up to date")
    expect(describeEntry(i18n, unchanged, names).explanation).toBe(
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

    expect(whatHappened(i18n, moved, names).text).toMatch(/^Moved from .+ in Personal → updated in Work$/)
  })

  it("lists several fields in a sentence", () => {
    const changed = entry({
      action: "update",
      reason: "occurrence_changed",
      category: "changed",
      changed_fields: ["time", "location", "conferencing"],
      event: recorded,
    })

    expect(whatHappened(i18n, changed, names).text).toBe(
      "Time, location, and video call links changed in Personal → updated in Work",
    )
    const pseudo = whatHappened(pseudoI18n(), changed, names).text
    for (const label of ["Time", "location", "video call links"]) expect(pseudo).toContain(pseudoize(label))
  })

  it("shows a changed field's values before and after, and what a list gained and lost", () => {
    const none = { before: null, after: null, before_time: null, after_time: null, added: [], removed: [] }

    expect(fieldChangeLines(i18n, { ...none, field: "description", before: "", after: "Dial in: 1234#" })).toMatchObject({
      label: "Description",
      before: "(empty)",
      after: "Dial in: 1234#",
      added: [],
      removed: [],
    })
    expect(fieldChangeLines(i18n, { ...none, field: "guests", added: ["cleo@example.com"], removed: ["ben@example.com"] })).toMatchObject({
      label: "Guests",
      before: null,
      after: null,
      added: ["cleo@example.com"],
      removed: ["ben@example.com"],
    })
    expect(fieldChangeLines(i18n, { ...none, field: "response", before: "tentative", after: "accepted" })).toMatchObject({
      label: "Your response",
      before: "Maybe",
      after: "Yes",
    })
    const moved = fieldChangeLines(i18n, {
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
    const listing = changeListing(i18n, {
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
    expect(["title", "time", "description", "location", "guests", "recurrence", "conferencing"].map((field) => fieldLabel(i18n, field))).toEqual([
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

describe("changeMark", () => {
  it("gives every outcome one sign, read like a diff", () => {
    expect(changeMark("added", "create")).toBe("added")
    expect(changeMark("repaired", "create")).toBe("added")
    expect(changeMark("removed", "delete")).toBe("removed")
    expect(changeMark("rule", "rule_removed")).toBe("removed")
    expect(changeMark("repaired", "update")).toBe("changed")
    expect(changeMark("updated", "update")).toBe("changed")
    expect(changeMark("rule", "policy_changed")).toBe("changed")
    expect(changeMark("blocked", "conflict")).toBe("blocked")
    expect(changeMark("skipped", "ignore")).toBe("skipped")
    expect(changeMark("current", "ignore")).toBe("current")
  })

  it("is what each line of What happened carries", () => {
    expect(whatHappened(i18n, entry({ action: "create", reason: "projection_missing", category: "changed" }), null).mark).toBe(
      "added",
    )
  })
})
