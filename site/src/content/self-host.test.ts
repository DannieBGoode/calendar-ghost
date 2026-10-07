import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { REPO_URL } from "../links"
import { SELF_HOST_COMMANDS } from "./self-host"

// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// rewrite (which serves the path over http://, not file://) from matching this call.
const here = import.meta.url
const README = readFileSync(new URL("../../../README.md", here), "utf8")

describe("self-host commands", () => {
  it("clone this repository", () => {
    expect(SELF_HOST_COMMANDS[0]).toBe(`git clone ${REPO_URL}.git && cd calendar-ghost`)
  })

  it("match the README's quick start, so the page never drifts from it", () => {
    for (const command of SELF_HOST_COMMANDS.slice(1)) expect(README).toContain(command)
  })
})
