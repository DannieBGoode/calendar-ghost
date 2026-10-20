import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/lib/api"

const KEY = ["identity-email"] as const

/** The administrator's current attempt, polled only while the worker has work. */
export function useIdentityEmail() {
  const client = useQueryClient()
  const readiness = useQuery({
    queryKey: KEY,
    queryFn: api.identityEmail,
    refetchInterval: (query) => {
      const state = query.state.data?.test_state
      return state === "queued" || state === "sending" ? 1000 : false
    },
  })
  const test = useMutation({
    mutationFn: api.testIdentityEmail,
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  })
  return { readiness, test }
}
