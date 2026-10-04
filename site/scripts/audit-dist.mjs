import { readdirSync, readFileSync } from "node:fs"
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

if (problems.length > 0) {
  console.error(problems.join("\n"))
  process.exit(1)
}
console.log("dist audit: no third-party requests; every page has a title, description, and canonical URL")
