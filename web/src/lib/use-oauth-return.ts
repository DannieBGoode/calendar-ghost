import { useEffect, useState } from "react"

import type { CalendarProvider } from "@/lib/api"
import {
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
  onAuthorizationStart,
} from "@/lib/oauth-redirect"

/** A provider that returns somewhere other than this address, and where. */
export type OAuthMismatch = { redirectOrigin: string; redirectUri: string; provider: CalendarProvider }

export type OAuthReturn = {
  /** Every provider that returns elsewhere; only the one a waiting connection began with while one waits. */
  mismatches: OAuthMismatch[]
  awaiting: boolean
  dismiss: () => void
}

/**
 * Whether providers return somewhere else, and whether a connection started in this browser may
 * be waiting for that return address. While one waits, only the provider it began with counts.
 * Read the OAuth outcome first: returning ends the attempt. A connection started from this page
 * while it stays open, in a new tab, waits here at once.
 */
export function useOAuthReturn(providers: readonly CalendarProvider[]): OAuthReturn {
  const [started, setStarted] = useState(() => authorizationAwaitingReturn())
  useEffect(() => onAuthorizationStart(() => setStarted(authorizationAwaitingReturn())), [])
  const candidates = started ? providers.filter((provider) => provider.kind === started) : providers
  const mismatches = candidates.flatMap((provider) => {
    const mismatch = oauthRedirectMismatch(provider.redirect_uri, window.location.origin)
    return mismatch ? [{ redirectOrigin: mismatch.redirectOrigin, redirectUri: provider.redirect_uri, provider }] : []
  })
  return {
    mismatches,
    awaiting: started !== null,
    dismiss: () => {
      clearAuthorizationStart()
      setStarted(null)
    },
  }
}
