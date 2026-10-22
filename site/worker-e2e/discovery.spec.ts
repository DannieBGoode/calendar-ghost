import { expect, test } from "@playwright/test"
import { DOC_PAGES } from "../src/docs/pages"

for (const path of ["/", ...DOC_PAGES.map(({ slug }) => `/docs/${slug}/`)]) {
  test(`discovers real guides and negotiates both representations at ${path}`, async ({ request }) => {
    const html = await request.get(path)
    expect(html.status()).toBe(200)
    expect(html.headers()["content-type"]).toContain("text/html")
    expect(html.headers().vary).toContain("Accept")
    expect(html.headers()["content-signal"]).toBe("search=yes, ai-input=yes, ai-train=no")
    expect(html.headers().link).toContain('</docs/self-hosting>; rel="describedby"')
    expect(html.headers().link).toContain('#6-connect-monitors-and-agents>; rel="describedby"')

    const markdown = await request.get(path, { headers: { Accept: "text/markdown" } })
    expect(markdown.status()).toBe(200)
    expect(markdown.headers()["content-type"]).toBe("text/markdown; charset=utf-8")
    expect(markdown.headers().vary).toContain("Accept")
    expect(markdown.headers()["content-signal"]).toBe("search=yes, ai-input=yes, ai-train=no")
    expect(await markdown.text()).toMatch(/^# /)
    expect(await markdown.text()).not.toContain("<script")
    expect(markdown.headers().etag).not.toBe(html.headers().etag)

    const direct = await request.get(`${path}index.md`)
    expect(direct.headers()["content-type"]).toBe("text/markdown; charset=utf-8")
    expect(await direct.text()).toBe(await markdown.text())
    expect(direct.headers()["content-signal"]).toBe("search=yes, ai-input=yes, ai-train=no")

    const head = await request.head(path, { headers: { Accept: "text/markdown" } })
    expect(head.status()).toBe(200)
    expect(head.headers()["content-type"]).toBe("text/markdown; charset=utf-8")
    expect(await head.body()).toHaveLength(0)

    const conditional = await request.get(path, { headers: { Accept: "text/markdown", "If-None-Match": markdown.headers().etag } })
    expect(conditional.status()).toBe(304)
    expect(conditional.headers().vary).toContain("Accept")
    const switched = await request.get(path, { headers: { Accept: "text/html", "If-None-Match": markdown.headers().etag } })
    expect(switched.status()).toBe(200)
    expect(switched.headers()["content-type"]).toContain("text/html")

    const excluded = await request.get(path, { headers: { Accept: "text/markdown;q=0, text/html" } })
    expect(excluded.headers()["content-type"]).toContain("text/html")
  })
}

test("robots declares the agreed usage preferences without blocking crawling", async ({ request }) => {
  const response = await request.get("/robots.txt")
  expect(response.status()).toBe(200)
  expect(await response.text()).toContain("User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\nAllow: /")
  expect(await response.text()).toContain("Sitemap: https://calendarghost.com/sitemap-index.xml")
})

test("unknown pages keep their 404 and assets keep their media type", async ({ request }) => {
  const missing = await request.get("/docs/not-a-guide", { headers: { Accept: "text/markdown" } })
  expect(missing.status()).toBe(404)
  expect(missing.headers()["content-type"]).toContain("text/html")
  expect(missing.headers().link).toBeUndefined()
  const favicon = await request.get("/favicon.svg", { headers: { Accept: "text/markdown" } })
  expect(favicon.status()).toBe(200)
  expect(favicon.headers()["content-type"]).toContain("image/svg+xml")
})
