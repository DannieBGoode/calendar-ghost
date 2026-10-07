import { existsSync, readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"
import { missingHeadTags, thirdPartyRequests } from "./audit.mjs"

const DIST = new URL("../dist/", import.meta.url).pathname
const HOST = "calendarghost.com"

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? files(join(directory, entry.name)) : [join(directory, entry.name)],
  )
}

const problems = []
for (const file of files(DIST)) {
  if (!/\.(html|css)$/.test(file)) continue
  const text = readFileSync(file, "utf8")
  const name = relative(DIST, file)
  for (const url of thirdPartyRequests(text, HOST)) problems.push(`${name}: third-party request ${url}`)
  if (file.endsWith(".html")) {
    for (const tag of missingHeadTags(text)) problems.push(`${name}: missing ${tag}`)
  }
}

// The pages rendered from the repository's documents (src/docs/pages.ts) are real content: each
// must be built, and listed in the sitemap.
const DOC_SLUGS = [...readFileSync(new URL("../src/docs/pages.ts", import.meta.url), "utf8").matchAll(/slug: "([^"]+)"/g)].map(
  (match) => match[1],
)
const sitemap = readFileSync(join(DIST, "sitemap-0.xml"), "utf8")
if (DOC_SLUGS.length === 0) problems.push("src/docs/pages.ts: no documentation pages found")
for (const slug of DOC_SLUGS) {
  if (!existsSync(join(DIST, "docs", slug, "index.html"))) problems.push(`docs/${slug}: not built`)
  if (!sitemap.includes(`https://${HOST}/docs/${slug}/`)) problems.push(`docs/${slug}: missing from the sitemap`)
}

if (problems.length > 0) {
  console.error(problems.join("\n"))
  process.exit(1)
}
console.log(
  "dist audit: no third-party requests; every page has a title, description, and canonical URL; every documentation page is built and in the sitemap",
)
