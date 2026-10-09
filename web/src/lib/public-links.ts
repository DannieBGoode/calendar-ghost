/** The pages someone opens from a link, before they have a session. */
export type PublicPage = "invitation" | "password-reset"

const PUBLIC_PATHS: Record<string, PublicPage> = {
  "/invitation": "invitation",
  "/password-reset": "password-reset",
}

export function publicPageAt(pathname: string): PublicPage | null {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  return PUBLIC_PATHS[normalized] ?? null
}

// The token rides in the fragment, which the browser never sends, so no server log keeps it.
export function invitationLink(origin: string, token: string): string {
  return `${origin}/invitation#${token}`
}

export function passwordResetLink(origin: string, token: string): string {
  return `${origin}/password-reset#${token}`
}

/** The token in a link's fragment; empty when there is none. */
export function linkToken(hash: string): string {
  const raw = hash.replace(/^#/, "")
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** Where a link stands: being checked, unreadable by the server, already spent, or ready to use. */
export type LinkStatus = "checking" | "failed" | "unusable" | "usable"

export function linkStatus(token: string, check: { data?: { usable: boolean } | undefined; error: unknown }): LinkStatus {
  if (!token) return "unusable"
  if (check.error) return "failed"
  if (!check.data) return "checking"
  return check.data.usable ? "usable" : "unusable"
}
