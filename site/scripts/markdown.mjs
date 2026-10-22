import { Window } from "happy-dom"
import TurndownService from "turndown"
import { gfm } from "turndown-plugin-gfm"

/** Convert the built page so copy, code samples, and rewritten repository links stay in sync. */
export function pageMarkdown(html) {
  const window = new Window({ settings: {
    disableJavaScriptEvaluation: true, disableJavaScriptFileLoading: true,
    disableCSSFileLoading: true, disableIframePageLoading: true,
  } })
  const document = new window.DOMParser().parseFromString(html, "text/html")
  const main = document.querySelector("main")
  const canonical = document.querySelector('link[rel="canonical"]')?.getAttribute("href")
  if (!main || !canonical) throw new Error("Markdown needs a main element and canonical URL")
  for (const node of main.querySelectorAll("script, style, template, svg, button, nav, [aria-hidden='true'], .doc-toc, .doc-source")) {
    node.remove()
  }
  // Islands can wrap list items. Restore their list parent before Turndown chooses list markers.
  for (const node of main.querySelectorAll("astro-island, astro-slot")) node.replaceWith(...node.childNodes)
  for (const node of main.querySelectorAll("a[href], img[src]")) {
    const attribute = node.tagName === "A" ? "href" : "src"
    node.setAttribute(attribute, new URL(node.getAttribute(attribute), canonical).href)
  }
  const converter = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced" })
  converter.use(gfm)
  return `${converter.turndown(main.innerHTML)}\n`
}
