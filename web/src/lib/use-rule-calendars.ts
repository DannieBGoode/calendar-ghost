import { useQueries } from "@tanstack/react-query"

import { api, type ConnectedAccount, type DiscoveredCalendar, type RuleDetail } from "@/lib/api"

export type CalendarsByAccount = Map<string, DiscoveredCalendar[] | undefined>

/** Calendar names for the rule's connected accounts, and whether the heading can name both yet. */
export function useRuleCalendars(detail: RuleDetail | undefined, accounts: ConnectedAccount[] | undefined) {
  const accountIds = detail
    ? [...new Set([detail.source.connected_account_id, detail.destination.connected_account_id])]
    : []
  const connectedIds = accountIds.filter(
    (id) => accounts?.find((account) => account.id === id)?.state === "connected",
  )
  const calendarQueries = useQueries({
    queries: connectedIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const calendarsByAccount: CalendarsByAccount = new Map(
    connectedIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
  )

  // Wait for calendar names so the focused heading never announces placeholder names; names
  // recorded when Google last listed the calendars serve until it answers again.
  const namesRecorded = Boolean(detail?.source.calendar_name && detail.destination.calendar_name)
  const namesReady = namesRecorded || calendarQueries.every((query) => !query.isPending)
  return { calendarsByAccount, namesReady }
}
