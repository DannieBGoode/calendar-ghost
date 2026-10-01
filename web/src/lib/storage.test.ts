import { describe, expect, it } from "vitest"

import { activitySummary, clearActivityBody, formatBytes, logSummary } from "@/lib/storage"

describe("formatBytes", () => {
  it("uses binary units with one decimal above a kilobyte", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(48.2 * 1024 * 1024)).toBe("48.2 MB")
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB")
  })
})

describe("activitySummary", () => {
  it("names the size, the entry count, and the oldest entry", () => {
    expect(
      activitySummary(
        {
          bytes: 48.2 * 1024 * 1024,
          reclaimable_bytes: 0,
          activity_entries: 61204,
          oldest_activity_at: "2026-06-12T09:00:00+00:00",
        },
        "en-GB",
      ),
    ).toBe("48.2 MB · 61,204 Activity entries since 12 Jun 2026")
  })

  it("says when there is no Activity yet", () => {
    expect(
      activitySummary(
        { bytes: 4096, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
        "en-GB",
      ),
    ).toBe("4.0 KB · No Activity yet")
  })
})

describe("logSummary", () => {
  it("names the size and the dates the logs cover", () => {
    expect(
      logSummary(
        {
          bytes: 7.9 * 1024 * 1024,
          files: 2,
          oldest_at: "2026-09-12T08:00:00+00:00",
          newest_at: "2026-10-01T18:04:12+00:00",
        },
        "en-GB",
      ),
    ).toBe("7.9 MB · 12 Sep – 1 Oct 2026")
  })

  it("explains when the installation keeps no log files", () => {
    expect(logSummary(null)).toBe("File logging is off. Container logs are still available.")
  })

  it("says when the logs are empty", () => {
    expect(logSummary({ bytes: 0, files: 0, oldest_at: null, newest_at: null })).toBe(
      "No log lines yet",
    )
  })
})

describe("clearActivityBody", () => {
  it("says how many entries go and that it cannot be undone", () => {
    expect(clearActivityBody(41880, 90)).toBe(
      "41,880 Activity entries older than 90 days will be removed. Each event's latest entry is kept. This cannot be undone.",
    )
    expect(clearActivityBody(1, 30)).toBe(
      "1 Activity entry older than 30 days will be removed. Each event's latest entry is kept. This cannot be undone.",
    )
    expect(clearActivityBody(0, 365)).toBe("Nothing is older than 365 days.")
  })
})
