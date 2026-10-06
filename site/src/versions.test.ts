import { readdirSync } from "node:fs"
import { join, relative } from "node:path"
import { describe, expect, it } from "vitest"
import { EARLIER_STATES, NON_PRODUCTION_PATHS, STATUS_LABELS, VERSIONS, VERSIONS_PATH, isLive, worktreeCommand } from "./versions"

// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// transform from rewriting this path (as in links.test.ts).
const here = import.meta.url
const PAGES = new URL("./pages/", here).pathname

/** Every route a page file under src/pages builds, as "/path". */
function routes(directory = PAGES): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return routes(path)
    const route = `/${relative(PAGES, path).replace(/\.astro$/, "")}`
    return [route.replace(/\/index$/, "") || "/"]
  })
}

const iterations = VERSIONS.flatMap((version) => version.iterations)

describe("the versions index", () => {
  it("lists every page route, so no iteration goes missing from it", () => {
    // Besides the iterations: the index itself, the 404, and the documentation pages (docs/pages.ts),
    // which are production content, not design iterations.
    const listed = new Set([...iterations.filter(isLive).map((iteration) => iteration.path), VERSIONS_PATH, "/404", "/docs/[slug]"])
    expect(routes().filter((route) => !listed.has(route))).toEqual([])
  })

  it("keeps no route for a discarded iteration", () => {
    const discarded = iterations.filter((iteration) => !isLive(iteration)).map((iteration) => iteration.path)
    expect(discarded).toEqual(["/home/hero-c"])
    expect(routes().filter((route) => discarded.includes(route))).toEqual([])
    expect(NON_PRODUCTION_PATHS).not.toContain("/home/hero-c")
  })

  it("lists each route once, with a date and the short commit that added it", () => {
    const paths = iterations.map((iteration) => iteration.path)
    expect(new Set(paths).size).toBe(paths.length)
    for (const iteration of iterations) {
      expect(iteration.path, iteration.name).toMatch(/^\//)
      expect(iteration.date, iteration.name).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(iteration.commit, iteration.name).toMatch(/^[0-9a-f]{7}$/)
      expect(iteration.tries, iteration.name).not.toContain("—")
    }
    for (const state of EARLIER_STATES) expect(state.commit).toMatch(/^[0-9a-f]{7}$/)
  })

  it("keeps every route but production out of the sitemap, the index included", () => {
    expect(NON_PRODUCTION_PATHS).not.toContain("/")
    expect(NON_PRODUCTION_PATHS).toContain(VERSIONS_PATH)
    expect(NON_PRODUCTION_PATHS).toEqual(
      expect.arrayContaining(["/bold", "/journey", "/home/hero-a", "/home/hero-b", "/home/hero-a2", "/home/hero-b2", "/home/hero-d", "/home/hero-e", "/home/hero-e2", "/home/hero-e3", "/home/hero-e4"]),
    )
  })

  it("says where each iteration stands: production is the one current page, and hero C is discarded", () => {
    for (const iteration of iterations) expect(Object.keys(STATUS_LABELS), iteration.name).toContain(iteration.status)
    expect(iterations.filter((iteration) => iteration.status === "current").map((iteration) => iteration.path)).toEqual(["/"])
    const heroC = iterations.find((iteration) => iteration.path === "/home/hero-c")
    expect(heroC?.status).toBe("discarded")
    expect(heroC?.commit).toBe("a7d8db3")
    expect(worktreeCommand("a7d8db3")).toBe("git worktree add ../calendar-ghost-a7d8db3 a7d8db3")
  })

  it("groups the home page first, with production as its first iteration", () => {
    expect(VERSIONS.map((version) => version.name)).toEqual(["Home", "Bold", "Journey"])
    expect(VERSIONS[0]!.iterations[0]!.path).toBe("/")
  })
})
