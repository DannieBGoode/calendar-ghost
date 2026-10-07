// Rewrites the links in a rendered repository document so they work on this site. A Markdown
// file links to its neighbours by relative path (`troubleshooting.md#reading-the-logs`,
// `adr/0019-....md`); on the site that path means nothing. A link to another rendered document
// becomes its page here, and a link to any other repository file goes to that file on GitHub.
// Links with a scheme, protocol-relative links, and in-page anchors stay as written. Images are
// left to Astro, which resolves a relative image next to the Markdown file into a built asset.
import { posix, relative, sep } from "node:path"
import { fileURLToPath } from "node:url"
import { REPO_URL } from "../links"
import { docPageFor } from "./pages"

export const REPO_BLOB = `${REPO_URL}/blob/main`

const HAS_SCHEME = /^[a-z][a-z\d+.-]*:/i

/** The href a link in `fromPath` (a repository path such as `docs/self-hosting.md`) should have. */
export function rewriteRepoLink(href: string, fromPath: string): string {
  if (href === "" || href.startsWith("#") || href.startsWith("//") || HAS_SCHEME.test(href)) return href
  const hashAt = href.indexOf("#")
  const path = hashAt === -1 ? href : href.slice(0, hashAt)
  const hash = hashAt === -1 ? "" : href.slice(hashAt)
  const target = path.startsWith("/")
    ? path.slice(1)
    : posix.normalize(posix.join(posix.dirname(fromPath), path))
  if (target.startsWith("..")) return href
  return `${docPageFor(target) ?? `${REPO_BLOB}/${target}`}${hash}`
}

/** A document's path in the repository (`docs/self-hosting.md`), or undefined for any file that
 * is not one of the repository's own documents (outside `repoRoot`, or inside the site). */
export function repoPathOf(file: URL | string | undefined, { repoRoot, siteRoot }: RepoRoots): string | undefined {
  if (!file) return undefined
  const path = file instanceof URL ? fileURLToPath(file) : file
  const fromRepo = relative(repoRoot, path)
  if (fromRepo.startsWith("..") || !relative(siteRoot, path).startsWith("..")) return undefined
  return fromRepo.split(sep).join("/")
}

interface RepoRoots {
  repoRoot: string
  siteRoot: string
}

interface LinkElement {
  tagName: string
  properties?: Record<string, unknown>
}

/**
 * A hast plugin for Astro's Markdown processor (Sätteri, astro.config.mjs). Its factory sees each
 * document before it is parsed and joins the pipeline only for the repository's own documents.
 */
export function repoLinksPlugin(roots: RepoRoots) {
  return ({ fileURL }: { fileURL: URL | undefined }) => {
    const fromPath = repoPathOf(fileURL, roots)
    if (!fromPath) return null
    return {
      name: "calendar-ghost-repo-links",
      element: {
        filter: ["a"],
        visit(node: LinkElement, context: { setProperty(node: LinkElement, key: string, value: unknown): void }) {
          const href = node.properties?.href
          if (typeof href === "string") context.setProperty(node, "href", rewriteRepoLink(href, fromPath))
        },
      },
    }
  }
}
