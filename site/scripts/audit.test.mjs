import { describe, expect, it } from "vitest"
import { missingHeadTags, thirdPartyRequests } from "./audit.mjs"

const HOST = "calendarghost.com"

describe("thirdPartyRequests", () => {
  it("allows the site's own and relative URLs", () => {
    const html = `<link rel="canonical" href="https://calendarghost.com/"><img src="/_astro/a.webp"><script src="/_astro/b.js"></script>`
    expect(thirdPartyRequests(html, HOST)).toEqual([])
  })

  it("ignores ordinary links, which load nothing", () => {
    expect(thirdPartyRequests(`<a href="https://github.com/x">GitHub</a>`, HOST)).toEqual([])
  })

  it("finds scripts, stylesheets, images, and srcset entries from other hosts", () => {
    const html = [
      `<script src="https://cdn.example.com/x.js"></script>`,
      `<link rel="stylesheet" href="//fonts.googleapis.com/css">`,
      `<source srcset="/a.webp 1x, https://img.example.org/b.webp 2x">`,
    ].join("")
    expect(thirdPartyRequests(html, HOST)).toEqual([
      "https://cdn.example.com/x.js",
      "//fonts.googleapis.com/css",
      "https://img.example.org/b.webp",
    ])
  })

  it("finds remote URLs in CSS", () => {
    expect(thirdPartyRequests(`@font-face{src:url("https://fonts.gstatic.com/f.woff2")}`, HOST)).toEqual([
      "https://fonts.gstatic.com/f.woff2",
    ])
  })
})

describe("missingHeadTags", () => {
  it("names each missing tag", () => {
    expect(missingHeadTags("<head></head>")).toEqual(["title", "description", "canonical"])
    expect(
      missingHeadTags(`<title>x</title><meta name="description" content="y"><link rel="canonical" href="z">`),
    ).toEqual([])
  })
})
