// The repository documents this site renders as pages (docs/pages.ts), read straight from the
// repository's `docs/` folder at build time.
import { defineCollection } from "astro:content"
import { glob } from "astro/loaders"
import { DOC_PAGES } from "./docs/pages"

export const collections = {
  docs: defineCollection({
    loader: glob({ pattern: DOC_PAGES.map((page) => page.source.replace(/^docs\//, "")), base: "../docs" }),
  }),
}
