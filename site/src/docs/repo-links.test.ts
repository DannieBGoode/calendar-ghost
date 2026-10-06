import { describe, expect, it } from "vitest"
import { REPO_BLOB, repoLinksPlugin, repoPathOf, rewriteRepoLink } from "./repo-links"

const FROM = "docs/self-hosting.md"

describe("links in a rendered repository document", () => {
  it("stay on the site when they point at another rendered document", () => {
    expect(rewriteRepoLink("troubleshooting.md#a-monitor-or-agent-cannot-read-status", FROM)).toBe(
      "/docs/troubleshooting#a-monitor-or-agent-cannot-read-status",
    )
    expect(rewriteRepoLink("self-hosting.md#6-connect-monitors-and-agents", "docs/troubleshooting.md")).toBe(
      "/docs/self-hosting#6-connect-monitors-and-agents",
    )
    expect(rewriteRepoLink("./troubleshooting.md", FROM)).toBe("/docs/troubleshooting")
  })

  it("go to the file on GitHub when it is not rendered here", () => {
    expect(rewriteRepoLink("data-ownership.md#backups-and-recovery", FROM)).toBe(
      `${REPO_BLOB}/docs/data-ownership.md#backups-and-recovery`,
    )
    expect(rewriteRepoLink("adr/0019-administrator-chosen-activity-retention.md", "docs/troubleshooting.md")).toBe(
      `${REPO_BLOB}/docs/adr/0019-administrator-chosen-activity-retention.md`,
    )
    expect(rewriteRepoLink("../README.md#3-start-the-service", FROM)).toBe(`${REPO_BLOB}/README.md#3-start-the-service`)
    expect(rewriteRepoLink("/LICENSE", FROM)).toBe(`${REPO_BLOB}/LICENSE`)
  })

  it("leave anchors, other sites, and mail links as written", () => {
    for (const href of [
      "#5-use-a-lan-host-or-https",
      "https://console.cloud.google.com/",
      "http://localhost:8000",
      "mailto:someone@example.com",
      "//example.com/x",
    ]) {
      expect(rewriteRepoLink(href, FROM)).toBe(href)
    }
  })

  it("join the Markdown pipeline only for the repository's own documents", () => {
    const roots = { repoRoot: "/repo", siteRoot: "/repo/site" }
    expect(repoPathOf(new URL("file:///repo/docs/self-hosting.md"), roots)).toBe("docs/self-hosting.md")
    expect(repoPathOf("/repo/site/src/notes.md", roots)).toBeUndefined()
    expect(repoPathOf("/elsewhere/notes.md", roots)).toBeUndefined()
    expect(repoLinksPlugin(roots)({ fileURL: new URL("file:///repo/site/src/notes.md") })).toBeNull()

    const plugin = repoLinksPlugin(roots)({ fileURL: new URL("file:///repo/docs/troubleshooting.md") })!
    const link = { tagName: "a", properties: { href: "deployment.md#docker-compose" } }
    const set: unknown[] = []
    plugin.element.visit(link, { setProperty: (_node, key, value) => set.push([key, value]) })
    expect(set).toEqual([["href", `${REPO_BLOB}/docs/deployment.md#docker-compose`]])
  })
})
