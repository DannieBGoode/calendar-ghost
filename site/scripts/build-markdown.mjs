import { readdirSync, readFileSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { pageMarkdown } from "./markdown.mjs"

function build(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) build(path)
    else if (entry.name === "index.html") {
      writeFileSync(join(directory, "index.md"), pageMarkdown(readFileSync(path, "utf8")))
    }
  }
}

build(new URL("../dist/", import.meta.url).pathname)
