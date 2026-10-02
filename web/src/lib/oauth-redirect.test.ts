import { afterEach, describe, expect, it, vi } from "vitest"

import {
  AUTHORIZATION_RETURN_MS,
  authorizationAwaitingReturn,
  clearAuthorizationStart,
  oauthRedirectMismatch,
  oauthReturnAtCurrentOrigin,
  recordAuthorizationStart,
} from "./oauth-redirect"

const localhostRedirect = "http://localhost:18000/api/v1/oauth/google/callback"

describe("oauthRedirectMismatch", () => {
  it("reports the Google return address when the browser uses a different host", () => {
    expect(oauthRedirectMismatch(localhostRedirect, "http://192.168.1.50:18000")).toEqual({
      redirectOrigin: "http://localhost:18000",
      currentOrigin: "http://192.168.1.50:18000",
    })
  })

  it("treats a different port or scheme as a different address", () => {
    expect(oauthRedirectMismatch(localhostRedirect, "http://localhost:8000")).not.toBeNull()
    expect(oauthRedirectMismatch(localhostRedirect, "https://localhost:18000")).not.toBeNull()
  })

  it("accepts the address Google will return to", () => {
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

  it("refuses anything that is not a Google return address", () => {
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

  it("is pending only while Google's return address still works", () => {
    const storage = memoryStorage()
    expect(authorizationAwaitingReturn(storage, 1_000)).toBe(false)
    recordAuthorizationStart(storage, 1_000)
    expect(authorizationAwaitingReturn(storage, 1_000 + AUTHORIZATION_RETURN_MS - 1)).toBe(true)
    expect(authorizationAwaitingReturn(storage, 1_000 + AUTHORIZATION_RETURN_MS)).toBe(false)
    expect(authorizationAwaitingReturn(storage, 999)).toBe(false)
  })

  it("falls back to quiet help when browser policy blocks storage", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("The operation is insecure.", "SecurityError")
      },
    })
    expect(() => recordAuthorizationStart()).not.toThrow()
    expect(() => clearAuthorizationStart()).not.toThrow()
    expect(authorizationAwaitingReturn()).toBe(false)
  })

  it("ends once the attempt returned", () => {
    const storage = memoryStorage()
    recordAuthorizationStart(storage, 1_000)
    clearAuthorizationStart(storage)
    expect(authorizationAwaitingReturn(storage, 2_000)).toBe(false)
  })
})
