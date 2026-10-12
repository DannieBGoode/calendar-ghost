import { afterEach, describe, expect, it, vi } from "vitest"

import { testI18n } from "@/i18n/testing"

import {
  AUTHORIZATION_RETURN_MS,
  OAUTH_OUTCOME_MESSAGES,
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
  oauthOutcome,
  oauthProvider,
  oauthReturnAtCurrentOrigin,
  recordAuthorizationStart,
} from "./oauth-redirect"

const localhostRedirect = "http://localhost:18000/api/v1/oauth/google/callback"

describe("oauthRedirectMismatch", () => {
  it("reports the provider's return address when the browser uses a different host", () => {
    expect(oauthRedirectMismatch(localhostRedirect, "http://192.168.1.50:18000")).toEqual({
      redirectOrigin: "http://localhost:18000",
      currentOrigin: "http://192.168.1.50:18000",
    })
  })

  it("treats a different port or scheme as a different address", () => {
    expect(oauthRedirectMismatch(localhostRedirect, "http://localhost:8000")).not.toBeNull()
    expect(oauthRedirectMismatch(localhostRedirect, "https://localhost:18000")).not.toBeNull()
  })

  it("accepts the address the provider will return to", () => {
    expect(oauthRedirectMismatch(localhostRedirect, "http://localhost:18000")).toBeNull()
    expect(
      oauthRedirectMismatch(
        "https://calendar.example.ts.net/api/v1/oauth/google/callback",
        "https://calendar.example.ts.net",
      ),
    ).toBeNull()
  })

  it("stays silent when the redirect URI is missing or unparseable", () => {
    expect(oauthRedirectMismatch(null, "http://192.168.1.50:18000")).toBeNull()
    expect(oauthRedirectMismatch("not a url", "http://192.168.1.50:18000")).toBeNull()
  })
})

describe("oauthOutcome", () => {
  it("reads the outcome the OAuth callback adds to the Settings address", () => {
    expect(oauthOutcome("?oauth=connected&provider=google")).toBe("connected")
    expect(oauthOutcome("?oauth=calendar_permission_required")).toBe("calendar_permission_required")
    expect(oauthOutcome("?tab=x&oauth=authorization_failed")).toBe("authorization_failed")
    expect(oauthProvider("?oauth=connected&provider=google")).toBe("google")
  })

  it("ignores a missing or unknown outcome", () => {
    expect(oauthOutcome("")).toBeNull()
    expect(oauthOutcome("?oauth=surprise")).toBeNull()
    expect(oauthProvider("?oauth=connected")).toBeNull()
  })

  it("names each outcome in the catalog, with the provider it was for", () => {
    const { t } = testI18n()
    const names = { account: "Example account", provider: "Example" }
    expect(t(OAUTH_OUTCOME_MESSAGES.connected.title, names)).toBe("Example account connected")
    expect(t(OAUTH_OUTCOME_MESSAGES.calendar_permission_required.title, names)).toBe("Calendar access wasn’t granted")
    expect(t(OAUTH_OUTCOME_MESSAGES.authorization_failed.title, names)).toBe("Example authorization could not be completed")
  })
})

describe("oauthReturnAtCurrentOrigin", () => {
  const lan = "http://192.168.1.50:18000"

  it("moves the address Google returned to onto this installation's origin", () => {
    const pasted = `  ${localhostRedirect}?state=s-1&code=4%2F0Ab&scope=email%20profile  `
    expect(oauthReturnAtCurrentOrigin(pasted, localhostRedirect, lan)).toBe(
      `${lan}/api/v1/oauth/google/callback?state=s-1&code=4%2F0Ab&scope=email%20profile`,
    )
  })

  it("carries a declined consent back too, so the attempt is cancelled", () => {
    const pasted = `${localhostRedirect}?error=access_denied&state=s-1`
    expect(oauthReturnAtCurrentOrigin(pasted, localhostRedirect, lan)).toBe(
      `${lan}/api/v1/oauth/google/callback?error=access_denied&state=s-1`,
    )
  })

  it("refuses anything that is not the provider's return address", () => {
    const refused = [
      "not a url",
      localhostRedirect,
      `${localhostRedirect}?code=4%2F0Ab`,
      `${localhostRedirect}?state=s-1`,
      "http://localhost:18000/settings?state=s-1&code=4%2F0Ab",
    ]
    for (const pasted of refused) {
      expect(oauthReturnAtCurrentOrigin(pasted, localhostRedirect, lan)).toBeNull()
    }
  })
})

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, value),
  }
}

describe("authorizationAwaitingReturn", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("names the provider while its return address still works", () => {
    const storage = memoryStorage()
    expect(authorizationAwaitingReturn(storage, 1_000)).toBeNull()
    recordAuthorizationStart("google", storage, 1_000)
    expect(authorizationAwaitingReturn(storage, 1_000 + AUTHORIZATION_RETURN_MS - 1)).toBe("google")
    expect(authorizationAwaitingReturn(storage, 1_000 + AUTHORIZATION_RETURN_MS)).toBeNull()
    expect(authorizationAwaitingReturn(storage, 999)).toBeNull()
  })

  it("forgets an attempt an earlier version recorded without its provider", () => {
    const storage = memoryStorage()
    storage.setItem("calendar-sync-authorization-started", "1000")
    expect(authorizationAwaitingReturn(storage, 2_000)).toBeNull()
  })

  it("falls back to quiet help when browser policy blocks storage", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("The operation is insecure.", "SecurityError")
      },
    })
    expect(() => recordAuthorizationStart("google")).not.toThrow()
    expect(() => clearAuthorizationStart()).not.toThrow()
    expect(authorizationAwaitingReturn()).toBeNull()
  })

  it("ends once the attempt returned", () => {
    const storage = memoryStorage()
    recordAuthorizationStart("google", storage, 1_000)
    clearAuthorizationStart(storage)
    expect(authorizationAwaitingReturn(storage, 2_000)).toBeNull()
  })
})
