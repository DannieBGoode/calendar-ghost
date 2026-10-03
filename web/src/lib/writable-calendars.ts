import type { DiscoveredCalendar } from "@/lib/api"

/** A read-only calendar can never be a Destination Calendar: writes to it would fail. */
export function writableCalendars(
  calendars: readonly DiscoveredCalendar[] | undefined,
): DiscoveredCalendar[] {
  return (calendars ?? []).filter((calendar) => calendar.writable)
}

/** The new-rule builder's default Destination Calendar: writable, and not `exclude` unless it is the only one. */
export function firstOtherCalendar(
  calendars: readonly DiscoveredCalendar[] | undefined,
  exclude: string | null,
): string {
  const writable = writableCalendars(calendars)
  return (writable.find((calendar) => calendar.id !== exclude) ?? writable[0])?.id ?? ""
}
