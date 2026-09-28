import { describe, expect, it } from "vitest"

import { oauthRedirectMismatch } from "./oauth-redirect"

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
