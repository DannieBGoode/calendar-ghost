type EndpointAccount = { email: string }
type EndpointCalendar = { id: string; summary: string }
type Endpoint = { calendar_id: string; calendar_name?: string | null }

export type RuleEndpointLabel = { calendar: string; account: string }

/** Names a rule's calendar as Google lists it now, else as it was last listed. */
export function ruleEndpointLabel(
  endpoint: Endpoint,
  account: EndpointAccount | undefined,
  calendars: readonly EndpointCalendar[] | undefined,
): RuleEndpointLabel {
  const email = account?.email
  const isPrimary = email !== undefined && endpoint.calendar_id === email
  const summary =
    calendars?.find((calendar) => calendar.id === endpoint.calendar_id)?.summary || endpoint.calendar_name
  const calendar = summary || (isPrimary ? email : "Secondary calendar")
  if (email === undefined) return { calendar, account: "Unknown account" }
  return { calendar, account: calendar === email ? "Primary calendar" : email }
}
