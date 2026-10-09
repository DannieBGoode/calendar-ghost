import { hashKey, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import type { SessionStatus } from "@/lib/api"

// The session and setup belong to the browser and the installation, not to any one User.
const SHARED_QUERIES: ReadonlySet<unknown> = new Set(["session", "setup"])
const SESSION = ["session"]

function signedInUser(session: SessionStatus | undefined): string | null {
  return session?.user?.id ?? null
}

function discardUserQueries(queryClient: QueryClient) {
  queryClient.removeQueries({ predicate: ({ queryKey }) => !SHARED_QUERIES.has(queryKey[0]) })
}

/**
 * Keeps one User's records from showing to another. Another tab of this browser may sign in as
 * someone else; the moment the session names a different User than the one signed in before,
 * every cached query but the session and setup is discarded, before the views render again.
 */
export function useUserScopedCache() {
  const queryClient = useQueryClient()
  useEffect(() => {
    const session = () => signedInUser(queryClient.getQueryData<SessionStatus>(SESSION))
    let current = session()
    return queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== "updated" || event.query.queryHash !== hashKey(SESSION)) return
      const next = session()
      if (next === null || next === current) return
      if (current !== null) discardUserQueries(queryClient)
      current = next
    })
  }, [queryClient])
}
