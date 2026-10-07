// The repository documents rendered as pages on this site, at build time, so the guide a visitor
// reads here is the same text as on GitHub. Each entry is a file in the repository's `docs/`
// folder and the page that shows it. Links between these files stay on the site; links to any
// other repository file go to that file on GitHub (repo-links.ts).
export const DOC_PAGES = [
  { slug: "self-hosting", source: "docs/self-hosting.md" },
  { slug: "troubleshooting", source: "docs/troubleshooting.md" },
] as const

export type DocSlug = (typeof DOC_PAGES)[number]["slug"]

/** Where a rendered document lives on the site. */
export function docPagePath(slug: DocSlug): string {
  return `/docs/${slug}`
}

/** The site page for a repository path, if that file is rendered here. */
export function docPageFor(repoPath: string): string | undefined {
  const page = DOC_PAGES.find((doc) => doc.source === repoPath)
  return page ? docPagePath(page.slug) : undefined
}
