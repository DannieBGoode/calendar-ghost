import { describe, expect, it, vi } from "vitest"
import { DOC_PAGES } from "../src/docs/pages"
import { pageResponse, prefersMarkdown } from "./pages"

describe("page negotiation", () => {
  it.each([
    ["", false], ["*/*", false], ["text/html, */*;q=0.8", false],
    ["text/markdown", true], ["text/markdown, text/html", true],
    ["TEXT/MARKDOWN; charset=utf-8", true],
    ["text/markdown;q=0", false], ["text/markdown;q=invalid", false],
    ["text/markdown;q=0.5, text/html", false],
    ["text/markdown;q=0.9, text/html;q=0.5", true],
    ["text/markdown;q=0, text/*;q=1", false],
    ["text/markdown;q=0.5, */*;q=1", false],
  ])("negotiates %s", (accept, expected) => expect(prefersMarkdown(accept)).toBe(expected))

  it.each(["/", ...DOC_PAGES.flatMap(({ slug }) => [`/docs/${slug}`, `/docs/${slug}/`])])("serves built Markdown at %s", async (path) => {
    const assets = vi.fn(async (_request: Request) => new Response("# Content", { headers: { etag: '"markdown"', vary: "Accept-Encoding" } }))
    const response = await pageResponse(new Request(`https://calendarghost.com${path}?from=agent`, {
      headers: { accept: "text/markdown" },
    }), { ASSETS: { fetch: assets } })
    const requested = new URL(assets.mock.calls[0][0].url)
    expect(requested.pathname).toBe(`${path.replace(/\/$/, "")}/index.md`)
    expect(requested.search).toBe("?from=agent")
    expect(await response.text()).toBe("# Content")
    expect(response.headers.get("content-type")).toBe("text/markdown; charset=utf-8")
    expect(response.headers.get("vary")).toBe("Accept-Encoding, Accept")
    expect(response.headers.get("etag")).toBe('"markdown"')
    expect(response.headers.get("link")).toContain('rel="describedby"')
  })

  it("keeps default HTML and existing headers, advertising the real guides", async () => {
    const request = new Request("https://calendarghost.com/")
    const assets = vi.fn(async () => new Response("<main>HTML</main>", { headers: {
      "content-type": "text/html", "cache-control": "public, max-age=60", vary: "Accept", link: '</other>; rel="alternate"',
    } }))
    const response = await pageResponse(request, { ASSETS: { fetch: assets } })
    expect(assets).toHaveBeenCalledWith(request)
    expect(await response.text()).toBe("<main>HTML</main>")
    expect(response.headers.get("content-type")).toBe("text/html")
    expect(response.headers.get("cache-control")).toBe("public, max-age=60")
    expect(response.headers.get("vary")).toBe("Accept")
    expect(response.headers.get("link")).toContain('</docs/self-hosting>; rel="describedby"')
    expect(response.headers.get("link")).toContain('</docs/self-hosting#6-connect-monitors-and-agents>; rel="describedby"')
    expect(response.headers.get("link")).toContain('</other>; rel="alternate"')
  })

  it("supports HEAD and conditional Markdown responses without bodies", async () => {
    for (const status of [200, 304]) {
      const assets = vi.fn(async (_request: Request) => new Response(null, { status }))
      const response = await pageResponse(new Request("https://calendarghost.com/", {
        method: "HEAD", headers: { accept: "text/markdown" },
      }), { ASSETS: { fetch: assets } })
      expect(assets.mock.calls[0][0].method).toBe("HEAD")
      expect(response.status).toBe(status)
      expect(await response.text()).toBe("")
      expect(response.headers.get("content-type")).toBe("text/markdown; charset=utf-8")
      expect(response.headers.get("vary")).toBe("Accept")
    }
  })

  it("preserves asset errors without relabeling them as Markdown", async () => {
    const response = await pageResponse(new Request("https://calendarghost.com/", { headers: { accept: "text/markdown" } }), {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404, headers: { "content-type": "text/html" } }) },
    })
    expect(response.status).toBe(404)
    expect(response.headers.get("content-type")).toBe("text/html")
    expect(response.headers.get("link")).toBeNull()
    expect(response.headers.get("vary")).toBe("Accept")
  })

  it("leaves unknown paths, assets and mutations to the static binding", async () => {
    for (const path of ["/docs/missing", "/favicon.svg", "/api/v1/status", "/mcp", "/index.md"]) {
      const request = new Request(`https://calendarghost.com${path}`, { headers: { accept: "text/markdown" } })
      const original = new Response("asset", { status: 404 })
      const assets = vi.fn(async () => original)
      expect(await pageResponse(request, { ASSETS: { fetch: assets } })).toBe(original)
      expect(assets).toHaveBeenCalledWith(request)
    }
    const request = new Request("https://calendarghost.com/", { method: "POST" })
    const assets = vi.fn(async () => new Response(null, { status: 405 }))
    expect((await pageResponse(request, { ASSETS: { fetch: assets } })).status).toBe(405)
    expect(assets).toHaveBeenCalledWith(request)
  })
})
