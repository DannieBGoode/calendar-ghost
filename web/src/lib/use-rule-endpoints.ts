import { useQueries, useQuery } from "@tanstack/react-query"

import { useI18n } from "@/i18n/provider"
import { api, type ConnectedAccount, type DiscoveredCalendar, type Rule } from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

export type RuleEndpoints = {
  source: { account: ConnectedAccount | undefined; calendars: DiscoveredCalendar[] | undefined; name: string }
  destination: { account: ConnectedAccount | undefined; calendars: DiscoveredCalendar[] | undefined; name: string }
  disconnected: ConnectedAccount[]
}

/** Accounts and calendar names for a set of rules, fetched once per account rather than per rule. */
export function useRuleEndpoints(rules: Pick<Rule, "source" | "destination">[]) {
  const i18n = useI18n()
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const accountsById = new Map((accounts.data ?? []).map((account) => [account.id, account]))
  const accountIds = [
    ...new Set(
      rules.flatMap((rule) => [rule.source.connected_account_id, rule.destination.connected_account_id]),
    ),
  ].filter((accountId) => accountsById.get(accountId)?.state === "connected")
  const calendarQueries = useQueries({
    queries: accountIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const calendarsByAccount = new Map(
    accountIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
  )

  function endpoints(rule: Pick<Rule, "source" | "destination">): RuleEndpoints {
    const side = (endpoint: Rule["source"]) => {
      const account = accountsById.get(endpoint.connected_account_id)
      const calendars = calendarsByAccount.get(endpoint.connected_account_id)
      return { account, calendars, name: ruleEndpointLabel(i18n, endpoint, account, calendars).calendar }
    }
    const source = side(rule.source)
    const destination = side(rule.destination)
    const disconnected = [source.account, destination.account].filter(
      (account, index, all): account is ConnectedAccount =>
        account?.state === "disconnected" && all.findIndex((candidate) => candidate?.id === account.id) === index,
    )
    return { source, destination, disconnected }
  }

  return { accounts, endpoints }
}
