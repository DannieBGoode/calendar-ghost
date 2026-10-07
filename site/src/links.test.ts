import { existsSync, readFileSync, statSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { DOC_PAGES, docPagePath } from "./docs/pages"
import { en } from "./i18n/en"
import {
  CHANGELOG_URL,
  DISCUSSIONS_URL,
  DOCS_URL,
  GUIDE_URL,
  INTEGRATIONS_URL,
  ISSUES_URL,
  LICENSE_URL,
  REPO_URL,
  SUPPORT_EMAIL_URL,
  TRADEMARKS_URL,
  TROUBLESHOOTING_URL,
  TRUST_DOCS,
} from "./links"

// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// rewrite (which serves the path over http://, not file://) from matching this call.
const here = import.meta.url
const BLOB = `${REPO_URL}/blob/main/`
const TREE = `${REPO_URL}/tree/main/`

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
    for (const url of [...TRUST_DOCS, INTEGRATIONS_URL, GUIDE_URL, TROUBLESHOOTING_URL, LICENSE_URL, TRADEMARKS_URL, CHANGELOG_URL]) {
      const [target, anchor] = url.split("#")
      // A page rendered on this site from a repository document, or a file on GitHub.
      const page = DOC_PAGES.find((doc) => docPagePath(doc.slug) === target)
      expect(page !== undefined || url.startsWith(BLOB), url).toBe(true)
      const path = page ? page.source : target!.slice(BLOB.length)
      const markdown = readFileSync(new URL(`../../${path}`, here), "utf8")
      if (anchor) expect(anchors(markdown), url).toContain(anchor)
    }
  })

  it("send the self-hosting guide and the monitors setup to the pages rendered here", () => {
    expect(GUIDE_URL).toBe("/docs/self-hosting")
    expect(INTEGRATIONS_URL).toBe("/docs/self-hosting#6-connect-monitors-and-agents")
  })

  it("send questions to Discussions and bugs to the issue chooser, whose templates exist", () => {
    expect(DISCUSSIONS_URL).toBe(`${REPO_URL}/discussions`)
    expect(ISSUES_URL).toBe(`${REPO_URL}/issues/new/choose`)
    expect(SUPPORT_EMAIL_URL).toBe("mailto:support@calendarghost.com")
    for (const template of ["config.yml", "bug-report.yml"]) {
      expect(existsSync(new URL(`../../.github/ISSUE_TEMPLATE/${template}`, here)), template).toBe(true)
    }
  })

  it("point the footer's documentation link at a folder that exists", () => {
    expect(DOCS_URL.startsWith(TREE)).toBe(true)
    const folder = new URL(`../../${DOCS_URL.slice(TREE.length)}`, here)
    expect(existsSync(folder) && statSync(folder).isDirectory()).toBe(true)
  })
})
