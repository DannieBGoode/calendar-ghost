import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"

/** How often the flag rechecks, as People's Installation Health card does. */
const REFRESH_INTERVAL = 60_000

/**
 * Whether something only the administrator can fix needs them: a stalled scheduler, or a likely
 * cause Installation Health suggests. People's own problems never raise it. Shares Installation
 * Health's query with People, so both always agree.
 */
export function useAdministratorFlag(enabled: boolean): boolean {
  const health = useQuery({
    queryKey: ["installation-health"],
    queryFn: api.installationHealth,
    refetchInterval: REFRESH_INTERVAL,
    enabled,
  })
  const report = health.data
  return enabled && report !== undefined && (report.hints.length > 0 || report.incidents.length > 0)
}
