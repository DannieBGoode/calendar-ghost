import react from "@astrojs/react"
import { satteri } from "@astrojs/markdown-satteri"
import sitemap from "@astrojs/sitemap"
import { defineConfig } from "astro/config"
import { fileURLToPath } from "node:url"
import { repoLinksPlugin } from "./src/docs/repo-links.ts"

export default defineConfig({
  site: "https://calendarghost.com",
  i18n: { defaultLocale: "en", locales: ["en"], routing: { prefixDefaultLocale: false } },
  integrations: [react(), sitemap()],
  // The repository's documents render as /docs pages (src/docs): their links to each other stay
  // on the site, every other repository link goes to GitHub. Code is highlighted at build time,
  // in a light and a dark theme that follow the page's (styles in pages/docs/[slug].astro).
  markdown: {
    processor: satteri({
      hastPlugins: [
        repoLinksPlugin({ repoRoot: fileURLToPath(new URL("..", import.meta.url)), siteRoot: fileURLToPath(new URL(".", import.meta.url)) }),
      ],
    }),
    shikiConfig: { themes: { light: "github-light-default", dark: "github-dark-default" }, defaultColor: false },
  },
  // Screenshots are imported from docs/assets so the page and the README never drift; the docs
  // pages read the repository's docs/ folder.
  vite: { server: { fs: { allow: [".."] } } },
})
