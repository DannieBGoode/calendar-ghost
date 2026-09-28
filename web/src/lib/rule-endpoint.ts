type EndpointAccount = { email: string }
type EndpointCalendar = { id: string; summary: string }

export type RuleEndpointLabel = { calendar: string; account: string }

export function ruleEndpointLabel(
  calendarId: string,
  account: EndpointAccount | undefined,
  calendars: readonly EndpointCalendar[] | undefined,
): RuleEndpointLabel {
  const email = account?.email
  const isPrimary = email !== undefined && calendarId === email
  const summary = calendars?.find((calendar) => calendar.id === calendarId)?.summary
  const calendar = summary || (isPrimary ? email : "Secondary calendar")
  if (email === undefined) return { calendar, account: "Unknown account" }
  return { calendar, account: calendar === email ? "Primary calendar" : email }
}
