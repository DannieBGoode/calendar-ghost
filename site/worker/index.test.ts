import { readFileSync } from "node:fs"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ANALYTICS_PREFIX, COLLECT_PATH, TRACKER_PATH } from "../src/lib/analytics"
import worker, { UMAMI_COLLECT, UMAMI_TRACKER, type Env } from "./index"

const ORIGIN = "https://calendarghost.com"
// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// rewrite (which serves the path over http://, not file://) from matching this call.
const here = import.meta.url

function env() {
  const assets = vi.fn(async () => new Response("asset"))
  return { env: { ASSETS: { fetch: assets } } satisfies Env, assets }
}

afterEach(() => vi.unstubAllGlobals())

describe("the site Worker", () => {
  it("serves Umami's tracker from this origin, cached for a day", async () => {
    const upstream = vi.fn(async () => new Response("tracker();"))
    vi.stubGlobal("fetch", upstream)
    const response = await worker.fetch(new Request(`${ORIGIN}${TRACKER_PATH}`), env().env)
    expect(upstream).toHaveBeenCalledWith(UMAMI_TRACKER)
    expect(await response.text()).toBe("tracker();")
    expect(response.headers.get("content-type")).toBe("text/javascript; charset=utf-8")
    expect(response.headers.get("cache-control")).toBe("public, max-age=86400")
  })

  it("forwards an event with the tracker's headers and the visitor's address, and nothing else", async () => {
    const upstream = vi.fn(async (_url: string, _init: RequestInit) => Response.json({ cache: "token" }))
    vi.stubGlobal("fetch", upstream)
    const body = JSON.stringify({ type: "event", payload: { url: "/" } })
    const request = new Request(`${ORIGIN}${COLLECT_PATH}`, {
      method: "POST",
      body,
      headers: {
        "content-type": "application/json",
        "user-agent": "Firefox",
        "x-umami-website-id": "site-id",
        "x-umami-hostname": "calendarghost.com",
        "x-umami-cache": "previous",
        "cf-connecting-ip": "203.0.113.7",
        cookie: "never=forwarded",
      },
    })
    const response = await worker.fetch(request, env().env)

    const [url, init] = upstream.mock.calls[0]
    expect(url).toBe(UMAMI_COLLECT)
    expect(init.method).toBe("POST")
    expect(init.body).toBe(body)
    expect(Object.fromEntries(new Headers(init.headers))).toEqual({
      "content-type": "application/json",
      "user-agent": "Firefox",
      "x-umami-website-id": "site-id",
      "x-umami-hostname": "calendarghost.com",
      "x-umami-cache": "previous",
      "x-forwarded-for": "203.0.113.7",
    })
    expect(await response.json()).toEqual({ cache: "token" })
    expect(response.headers.get("cache-control")).toBe("no-store")
  })

  it("serves every other request from the static files, and never forwards them", async () => {
    const upstream = vi.fn()
    vi.stubGlobal("fetch", upstream)
    for (const request of [
      new Request(`${ORIGIN}/`),
      new Request(`${ORIGIN}${ANALYTICS_PREFIX}/other`),
      new Request(`${ORIGIN}${COLLECT_PATH}`),
      new Request(`${ORIGIN}${TRACKER_PATH}`, { method: "POST" }),
    ]) {
      const { env: bindings, assets } = env()
      expect(await (await worker.fetch(request, bindings)).text()).toBe("asset")
      expect(assets).toHaveBeenCalledWith(request)
    }
    expect(upstream).not.toHaveBeenCalled()
  })

  it("runs first for exactly the analytics paths (wrangler.jsonc)", () => {
    const config = readFileSync(new URL("../wrangler.jsonc", here), "utf8")
    expect(config).toContain(`"run_worker_first": ["${ANALYTICS_PREFIX}/*"]`)
    expect(config).toContain(`"main": "worker/index.ts"`)
  })
})
