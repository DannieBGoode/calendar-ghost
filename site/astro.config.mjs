import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"
import { defineConfig } from "astro/config"
import { NON_PRODUCTION_PATHS } from "./src/versions.ts"

export default defineConfig({
  site: "https://calendarghost.com",
  i18n: { defaultLocale: "en", locales: ["en"], routing: { prefixDefaultLocale: false } },
  integrations: [
    react(),
    // Versions and iterations kept for side-by-side comparison (src/versions.ts) carry `noindex`
    // and stay out of the sitemap.
    sitemap({ filter: (page) => !NON_PRODUCTION_PATHS.some((path) => new URL(page).pathname.replace(/\/$/, "") === path) }),
  ],
  // Screenshots are imported from docs/assets so the page and the README never drift.
  vite: { server: { fs: { allow: [".."] } } },
})
