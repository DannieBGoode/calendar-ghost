// Requests a page makes on its own: scripts, stylesheets and other <link>s, media, and frames.
// Plain <a href> links load nothing and are allowed anywhere.
const REQUEST_ATTRIBUTE = /<(?:script|img|source|link|iframe|video|audio)\b[^>]*?\s(?:src|href|srcset)=["']([^"']+)["']/gi
const CSS_URL = /url\(\s*["']?([^"')]+)["']?\s*\)/gi
const ABSOLUTE = /^(?:https?:)?\/\//i

export function thirdPartyRequests(text, allowedHost) {
  const urls = [...text.matchAll(REQUEST_ATTRIBUTE), ...text.matchAll(CSS_URL)].flatMap((match) =>
    match[1].split(",").map((entry) => entry.trim().split(/\s+/)[0]),
  )
  return urls.filter((url) => ABSOLUTE.test(url) && new URL(url, `https://${allowedHost}`).host !== allowedHost)
}

export function missingHeadTags(html) {
  const checks = {
    title: /<title>[^<]+<\/title>/i,
    description: /<meta\s+name="description"\s+content="[^"]+"/i,
    canonical: /<link\s+rel="canonical"\s+href="[^"]+"/i,
  }
  return Object.entries(checks)
    .filter(([, pattern]) => !pattern.test(html))
    .map(([name]) => name)
}
