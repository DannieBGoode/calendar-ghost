export type OAuthRedirectMismatch = {
  redirectOrigin: string
  currentOrigin: string
}

// Google returns the browser to the configured redirect URI, so an authorization started from
// any other origin lands on an address that may not reach this installation.
export function oauthRedirectMismatch(
  redirectUri: string | null,
  currentOrigin: string,
): OAuthRedirectMismatch | null {
  if (!redirectUri) return null
  let redirectOrigin: string
  try {
    redirectOrigin = new URL(redirectUri).origin
  } catch {
    return null
  }
  return redirectOrigin === currentOrigin ? null : { redirectOrigin, currentOrigin }
}

// The address Google sent the browser to, moved to the origin this installation is open at. The
// callback's one-use, 10-minute state protects it, so only the path and query need to carry over.
export function oauthReturnAtCurrentOrigin(
  pasted: string,
  redirectUri: string,
  currentOrigin: string,
): string | null {
  let returned: URL
  let expected: URL
  try {
    returned = new URL(pasted.trim())
    expected = new URL(redirectUri)
  } catch {
    return null
  }
  const params = returned.searchParams
  const result = params.has("code") || params.has("error")
  if (returned.pathname !== expected.pathname || !params.get("state") || !result) return null
  return `${currentOrigin}${returned.pathname}${returned.search}`
}

const AUTHORIZATION_STARTED_KEY = "calendar-sync-google-authorization-started"
// Google's return address works once, for 10 minutes after the attempt starts.
export const AUTHORIZATION_RETURN_MS = 10 * 60 * 1000

type AuthorizationStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">

// Reading `window.localStorage` itself throws when browser policy blocks storage, so it is
// resolved here rather than as a default argument outside each function's guard.
function browserStorage(): AuthorizationStorage | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/** Remember, in this browser, when a Google connection was last started. */
export function recordAuthorizationStart(
  storage: AuthorizationStorage | null = browserStorage(),
  now = Date.now(),
) {
  try {
    storage?.setItem(AUTHORIZATION_STARTED_KEY, String(now))
  } catch {
    // Without storage the page just offers its quiet help instead of the pending step.
  }
}

export function clearAuthorizationStart(storage: AuthorizationStorage | null = browserStorage()) {
  try {
    storage?.removeItem(AUTHORIZATION_STARTED_KEY)
  } catch {
    // Nothing was recorded.
  }
}

/** Whether a connection started here may still be finished with Google's return address. */
export function authorizationAwaitingReturn(
  storage: AuthorizationStorage | null = browserStorage(),
  now = Date.now(),
): boolean {
  let started: number
  try {
    started = Number(storage?.getItem(AUTHORIZATION_STARTED_KEY))
  } catch {
    return false
  }
  return started > 0 && now >= started && now - started < AUTHORIZATION_RETURN_MS
}
