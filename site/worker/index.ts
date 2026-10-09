// The landing page is static files (wrangler.jsonc). This Worker runs only for the analytics paths
// (`run_worker_first`): it serves Umami Cloud's tracker and forwards the tracker's events, so the
// browser talks to calendarghost.com alone (src/lib/analytics.ts). This is Umami's own proxy
// recipe: https://docs.umami.is/docs/bypass-ad-blockers
import { COLLECT_PATH, TRACKER_PATH } from "../src/lib/analytics"

export const UMAMI_TRACKER = "https://cloud.umami.is/script.js"
export const UMAMI_COLLECT = "https://gateway.umami.is/api/send"
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
    return env.ASSETS.fetch(request)
  },
}

async function tracker(): Promise<Response> {
  const upstream = await fetch(UMAMI_TRACKER)
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": "text/javascript; charset=utf-8", "cache-control": "public, max-age=86400" },
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
