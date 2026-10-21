import { useEffect } from "react"

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
  const testedAt = readiness.data?.tested_at
  const accepted = readiness.data?.test_state === "accepted"
  useEffect(() => {
    if (!accepted || !testedAt) return
    void client.invalidateQueries({ queryKey: ["registration"] })
    void client.invalidateQueries({ queryKey: ["setup"] })
  }, [accepted, testedAt, client])
  const test = useMutation({
    mutationFn: api.testIdentityEmail,
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  })
  return { readiness, test }
}
