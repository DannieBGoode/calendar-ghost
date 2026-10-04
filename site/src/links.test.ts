import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { en } from "./i18n/en"
import { INTEGRATIONS_URL, REPO_URL, TRUST_DOCS } from "./links"

// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// rewrite (which serves the path over http://, not file://) from matching this call.
const here = import.meta.url
const BLOB = `${REPO_URL}/blob/main/`

/** The anchors GitHub gives a Markdown file's headings. */
function anchors(markdown: string): Set<string> {
  const headings = markdown.split("\n").filter((line) => /^#{1,6} /.test(line))
  return new Set(
    headings.map((line) =>
      line
        .replace(/^#+ /, "")
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N} _-]/gu, "")
        .replace(/ /g, "-"),
    ),
  )
}

describe("documentation links", () => {
  it("prove every trust claim, one link each", () => {
    expect(TRUST_DOCS).toHaveLength(en.trust.cards.length)
  })

  it("point at files and headings that exist in this repository", () => {
    for (const url of [...TRUST_DOCS, INTEGRATIONS_URL]) {
      expect(url.startsWith(BLOB), url).toBe(true)
      const [path, anchor] = url.slice(BLOB.length).split("#")
      const markdown = readFileSync(new URL(`../../${path}`, here), "utf8")
      if (anchor) expect(anchors(markdown), url).toContain(anchor)
    }
  })
})
