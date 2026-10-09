import { describe, expect, it } from "vitest"

import { invitationLink, linkToken, passwordResetLink, publicPageAt } from "./public-links"

describe("public links", () => {
  it("names the public page an address opens, before any session is needed", () => {
    expect(publicPageAt("/invitation")).toBe("invitation")
    expect(publicPageAt("/invitation/")).toBe("invitation")
    expect(publicPageAt("/password-reset")).toBe("password-reset")
    expect(publicPageAt("/overview")).toBeNull()
    expect(publicPageAt("/")).toBeNull()
  })

  it("carries the token in the fragment, so it never reaches a server log", () => {
    expect(invitationLink("https://ghost.example.test", "tok_en")).toBe("https://ghost.example.test/invitation#tok_en")
    expect(passwordResetLink("http://localhost:8000", "abc")).toBe("http://localhost:8000/password-reset#abc")
  })

  it("reads the token from the fragment", () => {
    expect(linkToken("#tok_en")).toBe("tok_en")
    expect(linkToken("")).toBe("")
    expect(linkToken("#")).toBe("")
    expect(linkToken("#a%2Db")).toBe("a-b")
    // A malformed escape is not a usable token, but must not throw.
    expect(linkToken("#%E0%A4%A")).toBe("%E0%A4%A")
  })
})
