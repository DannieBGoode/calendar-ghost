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
