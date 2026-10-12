import { useQuery } from "@tanstack/react-query"

import { api, type CalendarProvider } from "@/lib/api"

const NONE: readonly CalendarProvider[] = []

/** The providers Users can connect here; none while they load or could not be read. */
export function useProviders(): readonly CalendarProvider[] {
  return useQuery({ queryKey: ["providers"], queryFn: api.providers }).data ?? NONE
}
