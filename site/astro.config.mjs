import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"
import { defineConfig } from "astro/config"

// Design variants kept for side-by-side comparison; they carry `noindex` and stay out of the sitemap.
const VARIANT_PATHS = ["/bold", "/journey"]

export default defineConfig({
  site: "https://calendarghost.com",
  i18n: { defaultLocale: "en", locales: ["en"], routing: { prefixDefaultLocale: false } },
  integrations: [
    react(),
    sitemap({ filter: (page) => !VARIANT_PATHS.some((path) => new URL(page).pathname.replace(/\/$/, "") === path) }),
  ],
  // Screenshots are imported from docs/assets so the page and the README never drift.
  vite: { server: { fs: { allow: [".."] } } },
})
