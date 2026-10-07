// The home page's structured data (schema.org JSON-LD): it tells search engines this site is about
// one free, open-source app, and where its source lives. It names no rating or review, so Google
// shows no star snippet for it; it still helps search engines know what the page describes.
import type { Messages } from "../i18n"
import { LICENSE_URL, REPO_URL } from "../links"

export function homeStructuredData(m: Messages, site: URL): object {
  const home = new URL("/", site).href
  return {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "WebSite", "@id": `${home}#website`, url: home, name: m.brand, description: m.meta.description },
      {
        "@type": "SoftwareApplication",
        "@id": `${home}#app`,
        name: m.brand,
        description: m.meta.description,
        url: home,
        image: new URL("/og.png", site).href,
        applicationCategory: "UtilitiesApplication",
        operatingSystem: m.meta.operatingSystem,
        license: LICENSE_URL,
        isAccessibleForFree: true,
        offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
        sameAs: [REPO_URL],
      },
    ],
  }
}

/** The JSON for a `<script type="application/ld+json">`. `<` is escaped, so no text inside can
 * close the script element early. */
export function jsonLd(data: object): string {
  return JSON.stringify(data).replace(/</g, "\\u003c")
}
