import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"

import { ApiError, api } from "@/lib/api"
import { linkStatus, linkToken, type PublicPage } from "@/lib/public-links"

const CHECKS = {
  registration: (token: string) => api.checkRegistration(token),
  invitation: (token: string) => api.checkInvitation(token),
  "password-reset": (token: string) => api.checkPasswordReset(token),
}

/**
 * The token in this page's address. Opening a newer link in the same tab changes only the
 * fragment, without reloading, so the token follows it. An address that loses its token, as when
 * the page removes a spent one, keeps the link shown. `isCurrent` tells an older link's answer,
 * still arriving after a newer link opened, to change nothing.
 */
export function useLinkToken() {
  const [token, setToken] = useState(() => linkToken(window.location.hash))
  const current = useRef(token)
  useEffect(() => {
    const follow = () => {
      const next = linkToken(window.location.hash)
      if (!next) return
      current.current = next
      setToken(next)
    }
    window.addEventListener("hashchange", follow)
    return () => window.removeEventListener("hashchange", follow)
  }, [])
  const isCurrent = useCallback((candidate: string) => {
    // The address changes before `hashchange` reaches the page, so it is read here too.
    const live = linkToken(window.location.hash)
    return candidate === current.current && (!live || live === candidate)
  }, [])
  return { token, isCurrent }
}

/** Whether the server will still accept a link's token. A link without one is refused without asking. */
export function useLinkCheck<P extends Exclude<PublicPage, "provider-link">>(page: P, token: string) {
  const check = useQuery({
    queryKey: ["link-check", page, token],
    queryFn: () => CHECKS[page](token),
    enabled: token !== "",
    staleTime: Infinity,
    gcTime: 0,
  })
  // These check requests contain only a token. A validation refusal cannot be repaired
  // by retrying the same fragment; form/password validation keeps its own handling.
  const invalidToken = (page === "invitation" || page === "registration") && check.error instanceof ApiError && check.error.status === 422 && check.error.code === "invalid_request"
  return { status: invalidToken ? "unusable" as const : linkStatus(token, check), data: check.data as Awaited<ReturnType<(typeof CHECKS)[P]>> | undefined, error: check.error, recheck: check.refetch }
}
