import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { LICENSE_URL, REPO_URL } from "../links"
import { homeStructuredData, jsonLd } from "./structured-data"

const site = new URL("https://calendarghost.com")

describe("home structured data", () => {
  const graph = (homeStructuredData(en, site) as { "@graph": Record<string, unknown>[] })["@graph"]
  const app = graph.find((node) => node["@type"] === "SoftwareApplication")!

  it("describes the website and the free, open-source app with the page's own copy", () => {
    expect(graph.map((node) => node["@type"])).toEqual(["WebSite", "SoftwareApplication"])
    expect(app.name).toBe(en.brand)
    expect(app.description).toBe(en.meta.description)
    expect(app.url).toBe("https://calendarghost.com/")
    expect(app.offers).toEqual({ "@type": "Offer", price: "0", priceCurrency: "USD" })
    expect(app.license).toBe(LICENSE_URL)
    expect(app.sameAs).toEqual([REPO_URL])
  })

  it("cannot close its script element early", () => {
    const text = jsonLd({ name: "</script><script>alert(1)</script>" })
    expect(text).not.toContain("<")
    expect(JSON.parse(text)).toEqual({ name: "</script><script>alert(1)</script>" })
  })
})
