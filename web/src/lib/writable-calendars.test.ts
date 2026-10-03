import { describe, expect, it } from "vitest"

import { firstOtherCalendar, writableCalendars } from "./writable-calendars"

const writable = { id: "work@example.test", summary: "Work", writable: true, primary: true }
const readOnly = { id: "holidays@example.test", summary: "Holidays", writable: false, primary: false }
const otherWritable = { id: "team@example.test", summary: "Team", writable: true, primary: false }

describe("writableCalendars", () => {
  it("excludes a read-only calendar and keeps a writable one", () => {
    expect(writableCalendars([writable, readOnly])).toEqual([writable])
  })

  it("treats a missing list as empty", () => {
    expect(writableCalendars(undefined)).toEqual([])
  })
})

describe("firstOtherCalendar", () => {
  it("never picks a read-only calendar as the default", () => {
    expect(firstOtherCalendar([readOnly, writable], null)).toBe(writable.id)
  })

  it("skips the excluded calendar in favor of another writable one", () => {
    expect(firstOtherCalendar([writable, otherWritable], writable.id)).toBe(otherWritable.id)
  })

  it("falls back to the excluded calendar when it is the only writable one", () => {
    expect(firstOtherCalendar([writable], writable.id)).toBe(writable.id)
  })

  it("returns an empty string when nothing is writable", () => {
    expect(firstOtherCalendar([readOnly], null)).toBe("")
  })
})
