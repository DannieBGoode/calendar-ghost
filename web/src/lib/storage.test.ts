import { describe, expect, it } from "vitest"

import {
  activitySummary,
  canClearActivity,
  clearActivityConfirmation,
  clearedActivityMessage,
  countFailedConfirmation,
  formatBytes,
  logSummary,
} from "@/lib/storage"

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

  it("adds the space earlier clearing left to reclaim", () => {
    expect(
      activitySummary(
        {
          bytes: 260 * 1024,
          reclaimable_bytes: 1.2 * 1024 * 1024,
          activity_entries: 193,
          oldest_activity_at: "2026-06-12T09:00:00+00:00",
        },
        "en-GB",
      ),
    ).toBe("260.0 KB · 193 Activity entries since 12 Jun 2026 · 1.2 MB can be reclaimed")
    expect(
      activitySummary(
        { bytes: 4096, reclaimable_bytes: 2048, activity_entries: 0, oldest_activity_at: null },
        "en-GB",
      ),
    ).toBe("4.0 KB · No Activity yet · 2.0 KB can be reclaimed")
  })
})

describe("canClearActivity", () => {
  const usage = { bytes: 4096, oldest_activity_at: null }

  it("allows clearing while there is Activity or space to reclaim", () => {
    expect(canClearActivity({ ...usage, reclaimable_bytes: 0, activity_entries: 3 })).toBe(true)
    expect(canClearActivity({ ...usage, reclaimable_bytes: 2048, activity_entries: 0 })).toBe(true)
  })

  it("has nothing to do without either", () => {
    expect(canClearActivity({ ...usage, reclaimable_bytes: 0, activity_entries: 0 })).toBe(false)
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

describe("clearActivityConfirmation", () => {
  it("says how many entries go and that it cannot be undone", () => {
    expect(clearActivityConfirmation(41880, 90, 0)).toEqual({
      body: "41,880 Activity entries older than 90 days will be removed. Each event's latest entry is kept. This cannot be undone.",
      confirmLabel: "Clear Activity",
      pendingLabel: "Clearing…",
      canConfirm: true,
    })
    expect(clearActivityConfirmation(1, 30, 1024 * 1024).body).toBe(
      "1 Activity entry older than 30 days will be removed. Each event's latest entry is kept. This cannot be undone.",
    )
  })

  it("offers to reclaim the space an earlier clear left when nothing is old enough", () => {
    expect(clearActivityConfirmation(0, 90, 1.2 * 1024 * 1024)).toEqual({
      body: "Nothing is older than 90 days. 1.2 MB left by earlier clearing can still be reclaimed.",
      confirmLabel: "Reclaim space",
      pendingLabel: "Reclaiming…",
      canConfirm: true,
    })
  })

  it("has nothing to confirm when nothing is old enough and no space is left", () => {
    expect(clearActivityConfirmation(0, 365, 0)).toEqual({
      body: "Nothing is older than 365 days.",
      confirmLabel: "Clear Activity",
      pendingLabel: "Clearing…",
      canConfirm: false,
    })
  })
})

describe("clearedActivityMessage", () => {
  it("counts the cleared entries", () => {
    expect(clearedActivityMessage(41880, 0)).toBe("41,880 Activity entries were cleared.")
    expect(clearedActivityMessage(1, 0)).toBe("1 Activity entry was cleared.")
  })

  it("says when only space was reclaimed or nothing happened", () => {
    expect(clearedActivityMessage(0, 2048)).toBe(
      "The space left by earlier clearing was reclaimed.",
    )
    expect(clearedActivityMessage(0, 0)).toBe("Nothing was old enough to clear.")
  })
})

describe("countFailedConfirmation", () => {
  it("says the count failed and offers to count again", () => {
    expect(countFailedConfirmation("The database is busy.")).toEqual({
      body: "The entries to remove could not be counted: The database is busy.",
      confirmLabel: "Count again",
      pendingLabel: "Counting…",
      canConfirm: true,
    })
  })
})
