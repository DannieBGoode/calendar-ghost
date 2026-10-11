import type { MessageKey } from "@/i18n/types"

export type OAuthRedirectMismatch = {
  redirectOrigin: string
  currentOrigin: string
}

// A provider returns the browser to its configured redirect URI, so an authorization started from
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

// The address the provider sent the browser to, moved to the origin this installation is open at. The
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

const AUTHORIZATION_STARTED_KEY = "calendar-sync-authorization-started"
// A provider's return address works once, for 10 minutes after the attempt starts.
export const AUTHORIZATION_RETURN_MS = 10 * 60 * 1000

type AuthorizationStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
type AuthorizationStart = { at: number; provider: string }

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

/** Remember, in this browser, when a connection to `provider` was last started. */
export function recordAuthorizationStart(
  provider: string,
  storage: AuthorizationStorage | null = browserStorage(),
  now = Date.now(),
) {
  try {
    storage?.setItem(AUTHORIZATION_STARTED_KEY, JSON.stringify({ at: now, provider } satisfies AuthorizationStart))
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

function recordedStart(storage: AuthorizationStorage | null): AuthorizationStart | null {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(AUTHORIZATION_STARTED_KEY) ?? "null")
    if (typeof parsed !== "object" || parsed === null) return null
    const { at, provider } = parsed as Partial<AuthorizationStart>
    return typeof at === "number" && typeof provider === "string" ? { at, provider } : null
  } catch {
    return null
  }
}

/**
 * The provider a connection started here was begun with, while its return address may still
 * finish it; null when none is waiting.
 */
export function authorizationAwaitingReturn(
  storage: AuthorizationStorage | null = browserStorage(),
  now = Date.now(),
): string | null {
  const started = recordedStart(storage)
  if (!started || started.at <= 0 || now < started.at || now - started.at >= AUTHORIZATION_RETURN_MS) return null
  return started.provider
}

/** What the OAuth callback reports when it sends the browser back to Settings (`?oauth=`). */
export type OAuthOutcome = "connected" | "calendar_permission_required" | "authorization_failed"

export const OAUTH_OUTCOME_MESSAGES: Record<OAuthOutcome, { title: MessageKey; body: MessageKey }> = {
  connected: { title: "settings.oauthOutcome.connected.title", body: "settings.oauthOutcome.connected.body" },
  calendar_permission_required: {
    title: "settings.oauthOutcome.calendarPermissionRequired.title",
    body: "settings.oauthOutcome.calendarPermissionRequired.body",
  },
  authorization_failed: {
    title: "settings.oauthOutcome.authorizationFailed.title",
    body: "settings.oauthOutcome.authorizationFailed.body",
  },
}

/** The known outcome in a query string; an unknown or missing one shows nothing. */
export function oauthOutcome(search: string): OAuthOutcome | null {
  const value = new URLSearchParams(search).get("oauth")
  return value !== null && Object.hasOwn(OAUTH_OUTCOME_MESSAGES, value) ? (value as OAuthOutcome) : null
}

/** The Provider Kind whose connection flow returned, as the callback names it. */
export function oauthProvider(search: string): string | null {
  return new URLSearchParams(search).get("provider")
}
