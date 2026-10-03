import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string
}

const repositoryUrl = "https://github.com/DannieBGoode/calendar-ghost"

function currentRevision(): string | undefined {
  try {
    const revision = execFileSync("git", ["rev-parse", "HEAD"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim()
    return revision || undefined
  } catch {
    return undefined
  }
}

const configuredSourceUrl = process.env.CALENDAR_GHOST_SOURCE_URL?.trim().replace(/\/+$/, "")
const sourceRevision = process.env.GITHUB_SHA?.trim() || currentRevision() || "main"
const sourceUrl = configuredSourceUrl || `${repositoryUrl}/tree/${sourceRevision}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __SOURCE_URL__: JSON.stringify(sourceUrl),
  },
  resolve: {
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" },
  },
  build: {
    outDir: "../src/calendar_sync/interfaces/api/static",
    emptyOutDir: true,
  },
})
