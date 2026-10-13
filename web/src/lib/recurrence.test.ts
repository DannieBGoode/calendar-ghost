import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import { describeRepeat, nextOccurrence, readRepeat } from "./recurrence"

const i18n = testI18n()
// Tuesday 2 September 2025, 18:00 local time.
const firstTuesday = new Date(2025, 8, 2, 18, 0)

describe("readRepeat", () => {
  it("reads the parts it can step through", () => {
    expect(readRepeat(["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;COUNT=10"])).toEqual({
      frequency: "WEEKLY",
      interval: 2,
      byDay: [
        { weekday: 1, ordinal: null },
        { weekday: 4, ordinal: null },
      ],
      byMonthDay: [],
      count: 10,
      until: null,
      skipped: [],
    })
  })

  it("leaves a rule it would misread unread", () => {
    expect(readRepeat(["RRULE:FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,TU,WE,TH,FR"])).toBeNull()
    expect(readRepeat(["RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"])).toBeNull()
    expect(readRepeat(["RRULE:FREQ=MONTHLY;BYDAY=MO;BYMONTHDAY=1"])).toBeNull()
    expect(readRepeat(["RRULE:FREQ=WEEKLY;WKST=SU"])).toBeNull()
    expect(readRepeat(["RRULE:FREQ=WEEKLY", "RDATE:20250910"])).toBeNull()
    expect(readRepeat(["RDATE:20250902"])).toBeNull()
    expect(readRepeat(null)).toBeNull()
  })
})

describe("describeRepeat", () => {
  it.each([
    ["RRULE:FREQ=WEEKLY", "Weekly on Tuesday"],
    ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH", "Every 2 weeks on Monday and Thursday"],
    ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "Every weekday"],
    ["RRULE:FREQ=DAILY", "Every day"],
    ["RRULE:FREQ=MONTHLY;BYDAY=-1FR", "Monthly on the last Friday"],
    ["RRULE:FREQ=MONTHLY", "Monthly on day 2"],
    ["RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15", "Monthly on day 1 and day 15"],
    ["RRULE:FREQ=MONTHLY;BYDAY=2TU,-1FR", "Monthly on the second Tuesday and the last Friday"],
    // Every Monday of the month, or a day counted from its end, has no exact words here.
    ["RRULE:FREQ=MONTHLY;BYDAY=MO", "Repeats"],
    ["RRULE:FREQ=MONTHLY;BYMONTHDAY=-1", "Repeats"],
    ["RRULE:FREQ=YEARLY", "Yearly on September 2"],
    ["RRULE:FREQ=HOURLY", "Repeats"],
  ])("puts %s into words", (line, words) => {
    expect(describeRepeat(i18n, readRepeat([line]), firstTuesday)).toBe(words)
  })
})

describe("nextOccurrence", () => {
  const today = new Date(2025, 9, 13)

  it("finds a weekly series' next date from today", () => {
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=WEEKLY"]), firstTuesday, today)).toEqual(new Date(2025, 9, 14, 18, 0))
  })

  it("steps across months for daily and monthly series", () => {
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=DAILY;INTERVAL=3"]), firstTuesday, today)).toEqual(new Date(2025, 9, 14, 18, 0))
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=MONTHLY;BYDAY=-1FR"]), firstTuesday, today)).toEqual(new Date(2025, 9, 31, 18, 0))
  })

  it("starts an old series near the date asked for and finds the same date as walking it all", () => {
    const longAgo = new Date(2016, 2, 7, 9, 30)
    const from = new Date(2026, 9, 13, 12, 0)
    const rules = [
      "FREQ=DAILY",
      "FREQ=DAILY;INTERVAL=3",
      "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR",
      "FREQ=MONTHLY;BYDAY=-1FR",
      "FREQ=MONTHLY;BYMONTHDAY=31",
      "FREQ=YEARLY;INTERVAL=4",
    ]
    for (const rule of rules) {
      // A COUNT far beyond the dates asked for makes it walk from the first date, as before.
      const walked = nextOccurrence(readRepeat([`RRULE:${rule};COUNT=100000`]), longAgo, from, "Europe/Madrid")
      expect(nextOccurrence(readRepeat([`RRULE:${rule}`]), longAgo, from, "Europe/Madrid")).toEqual(walked)
    }
  })

  it("says when a series has ended", () => {
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=WEEKLY;COUNT=3"]), firstTuesday, today)).toBe("ended")
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=WEEKLY;UNTIL=20250930T000000Z"]), firstTuesday, today)).toBe("ended")
  })

  it("skips months without the day", () => {
    const thirtyFirst = new Date(2025, 7, 31, 9, 0)
    expect(nextOccurrence(readRepeat(["RRULE:FREQ=MONTHLY"]), thirtyFirst, today)).toEqual(new Date(2025, 9, 31, 9, 0))
  })
})

describe("nextOccurrence in the series' zone", () => {
  it("keeps a weekly New York meeting at 18:00 there across the DST change", () => {
    // 18:00 in New York on Tuesday 28 October 2025 is 22:00 UTC; after 2 November it is 23:00 UTC.
    const first = new Date(Date.UTC(2025, 9, 28, 22, 0))
    const next = nextOccurrence(readRepeat(["RRULE:FREQ=WEEKLY"]), first, new Date(Date.UTC(2025, 10, 3)), "America/New_York")
    expect(next).toEqual(new Date(Date.UTC(2025, 10, 4, 23, 0)))
  })

  it("skips a date the series excludes", () => {
    const next = nextOccurrence(
      readRepeat(["RRULE:FREQ=WEEKLY", "EXDATE;TZID=Europe/Madrid:20251014T180000"]),
      firstTuesday,
      new Date(2025, 9, 13),
    )
    expect(next).toEqual(new Date(2025, 9, 21, 18, 0))
  })

  it("reads an excluded time in UTC on the series' own day", () => {
    // Tuesday 13 October 2026, 18:00 in Los Angeles, is already 14 October in UTC.
    const first = new Date(Date.UTC(2026, 9, 7, 1, 0))
    const next = nextOccurrence(
      readRepeat(["RRULE:FREQ=WEEKLY", "EXDATE:20261014T010000Z"]),
      first,
      new Date(Date.UTC(2026, 9, 10)),
      "America/Los_Angeles",
    )
    expect(next).toEqual(new Date(Date.UTC(2026, 9, 21, 1, 0)))
  })
})

