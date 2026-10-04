import { useState } from "react"

import {
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
} from "@/lib/oauth-redirect"

export type GoogleReturn = {
  mismatch: { redirectOrigin: string; redirectUri: string } | null
  awaiting: boolean
  dismiss: () => void
}

/**
 * Whether Google returns somewhere else, and whether a connection started in this browser may be
 * waiting for that return address. Read the OAuth outcome first: returning ends the attempt.
 */
export function useGoogleReturn(redirectUri: string | null): GoogleReturn {
  const mismatch = oauthRedirectMismatch(redirectUri, window.location.origin)
  const [awaiting, setAwaiting] = useState(() => authorizationAwaitingReturn())
  return {
    mismatch: mismatch && redirectUri ? { redirectOrigin: mismatch.redirectOrigin, redirectUri } : null,
    awaiting,
    dismiss: () => {
      clearAuthorizationStart()
      setAwaiting(false)
    },
  }
}
