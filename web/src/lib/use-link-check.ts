import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import { linkStatus, linkToken, type PublicPage } from "@/lib/public-links"

const CHECKS: Record<PublicPage, (token: string) => Promise<{ usable: boolean }>> = {
  invitation: (token) => api.checkInvitation(token),
  "password-reset": (token) => api.checkPasswordReset(token),
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
  const isCurrent = useCallback((candidate: string) => candidate === current.current, [])
  return { token, isCurrent }
}

/** Whether the server will still accept a link's token. A link without one is refused without asking. */
export function useLinkCheck(page: PublicPage, token: string) {
  const check = useQuery({
    queryKey: ["link-check", page, token],
    queryFn: () => CHECKS[page](token),
    enabled: token !== "",
    staleTime: Infinity,
  })
  return { status: linkStatus(token, check), error: check.error }
}
