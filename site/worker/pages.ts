import { DOC_PAGES } from "../src/docs/pages"
import type { Env } from "./index"

const PAGE_PATHS = new Set(["/", ...DOC_PAGES.map(({ slug }) => `/docs/${slug}`)])
const GUIDES = '</docs/self-hosting>; rel="describedby"; type="text/html", </docs/self-hosting#6-connect-monitors-and-agents>; rel="describedby"; type="text/html"'

/** Require an explicit Markdown preference; a browser's wildcard keeps HTML. */
export function prefersMarkdown(accept: string): boolean {
  const ranges = accept.toLowerCase().split(",").map((range) => {
    const [type, ...parameters] = range.trim().split(";")
    const quality = parameters.map((parameter) => parameter.trim()).find((parameter) => parameter.startsWith("q="))
    const q = quality === undefined ? 1 : Number(quality.slice(2))
    return { type: type.trim(), q: Number.isFinite(q) && q >= 0 && q <= 1 ? q : 0 }
  })
  const quality = (type: string): number => {
    for (const candidate of [type, "text/*", "*/*"]) {
      const matches = ranges.filter((range) => range.type === candidate)
      if (matches.length) return Math.max(...matches.map((range) => range.q))
    }
    return 0
  }
  return ranges.some(({ type }) => type === "text/markdown") && quality("text/markdown") > 0
    && quality("text/markdown") >= quality("text/html")
}

/** Discovery and negotiation apply only to published pages, never unknown paths or analytics. */
export async function pageResponse(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url)
  const path = url.pathname === "/" ? "/" : url.pathname.replace(/\/$/, "")
  if (!PAGE_PATHS.has(path) || !["GET", "HEAD"].includes(request.method)) return env.ASSETS.fetch(request)
  const markdown = prefersMarkdown(request.headers.get("accept") ?? "")
  if (markdown) url.pathname = `${path === "/" ? "" : path}/index.md`
  const response = await env.ASSETS.fetch(markdown ? new Request(url, request) : request)
  const headers = new Headers(response.headers)
  const vary = headers.get("vary")
  if (vary !== "*" && !vary?.split(",").some((value) => value.trim().toLowerCase() === "accept")) {
    headers.set("vary", vary ? `${vary}, Accept` : "Accept")
  }
  if (response.ok || response.status === 304) {
    headers.append("link", GUIDES)
    headers.append("link", `<${path === "/" ? "" : path}/index.md>; rel="alternate"; type="text/markdown"`)
    if (markdown) headers.set("content-type", "text/markdown; charset=utf-8")
  }
  return new Response(request.method === "HEAD" ? null : response.body, { status: response.status, headers })
}
