import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"
import { defineConfig } from "astro/config"

export default defineConfig({
  site: "https://calendarghost.com",
  i18n: { defaultLocale: "en", locales: ["en"], routing: { prefixDefaultLocale: false } },
  integrations: [react(), sitemap()],
  // Screenshots are imported from docs/assets so the page and the README never drift.
  vite: { server: { fs: { allow: [".."] } } },
})
