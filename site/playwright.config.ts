import { defineConfig, devices } from "@playwright/test"

// E2E_PORT runs the suite against a preview on another port, for when 4321 is taken by a dev server.
const PORT = Number(process.env.E2E_PORT ?? 4321)

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: `http://localhost:${PORT}` },
  webServer: {
    command: `npm run preview -- --port ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    // Astro's preview CLI auto-backgrounds itself (and exits immediately) when it detects it is
    // being run by a coding agent, which races with Playwright's "wait for the server" check.
    // This opts back into the normal foreground server Playwright expects; it is a no-op outside
    // an agent environment.
    env: { ASTRO_PREVIEW_BACKGROUND: "1" },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
