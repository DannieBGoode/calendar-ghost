import { useState } from "react"

import type { CalendarProvider } from "@/lib/api"
import {
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
} from "@/lib/oauth-redirect"

export type OAuthReturn = {
  /** The provider that returns somewhere other than this address, and where. */
  mismatch: { redirectOrigin: string; redirectUri: string; provider: CalendarProvider } | null
  awaiting: boolean
  dismiss: () => void
}

/**
 * Whether a provider returns somewhere else, and whether a connection started in this browser may
 * be waiting for that return address. The provider a waiting connection began with comes first;
 * otherwise the first provider that returns elsewhere. Read the OAuth outcome first: returning
 * ends the attempt.
 */
export function useOAuthReturn(providers: readonly CalendarProvider[]): OAuthReturn {
  const [started, setStarted] = useState(() => authorizationAwaitingReturn())
  const candidates = started ? providers.filter((provider) => provider.kind === started) : providers
  const provider = candidates.find((candidate) => oauthRedirectMismatch(candidate.redirect_uri, window.location.origin))
  const mismatch = provider ? oauthRedirectMismatch(provider.redirect_uri, window.location.origin) : null
  return {
    mismatch:
      mismatch && provider ? { redirectOrigin: mismatch.redirectOrigin, redirectUri: provider.redirect_uri, provider } : null,
    awaiting: started !== null,
    dismiss: () => {
      clearAuthorizationStart()
      setStarted(null)
    },
  }
}
