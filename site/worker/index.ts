// The landing page is static files (wrangler.jsonc). This Worker adds discovery headers and
// negotiates built Markdown for published pages. It also serves Umami's analytics paths, so the
// browser talks to calendarghost.com alone (src/lib/analytics.ts). This is Umami's own proxy
// recipe: https://docs.umami.is/docs/bypass-ad-blockers
import { COLLECT_PATH, TRACKER_PATH } from "../src/lib/analytics"
import { pageResponse } from "./pages"
import { UMAMI_COLLECT, UMAMI_TRACKER } from "./umami"

/** What Umami reads from the tracker's request: the website, the page's host, the session cache,
 * and the browser and device (from the user agent). */
const FORWARDED_HEADERS = ["content-type", "user-agent", "x-umami-website-id", "x-umami-hostname", "x-umami-cache"]

export interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url)
    if (pathname === TRACKER_PATH && request.method === "GET") return tracker()
    if (pathname === COLLECT_PATH && request.method === "POST") return collect(request)
    return pageResponse(request, env)
  },
}

// Only a good tracker is cached: a failed response, kept for a day, would stop all counting long
// after Umami recovered.
async function tracker(): Promise<Response> {
  const upstream = await fetch(UMAMI_TRACKER)
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/javascript; charset=utf-8",
      "cache-control": upstream.ok ? "public, max-age=86400" : "no-store",
    },
  })
}

// Umami finds the visitor's country, and tells one visitor from another, by the IP address it is
// given. Without X-Forwarded-For, every visit would seem to come from this Worker.
async function collect(request: Request): Promise<Response> {
  const headers = new Headers()
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name)
    if (value !== null) headers.set(name, value)
  }
  const ip = request.headers.get("cf-connecting-ip")
  if (ip) headers.set("x-forwarded-for", ip)
  const upstream = await fetch(UMAMI_COLLECT, { method: "POST", headers, body: await request.text() })
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
  })
}
