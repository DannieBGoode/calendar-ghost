import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: "http://localhost:4321" },
  webServer: {
    command: "npm run preview -- --port 4321",
    url: "http://localhost:4321",
    reuseExistingServer: !process.env.CI,
    // Astro's preview CLI auto-backgrounds itself (and exits immediately) when it detects it is
    // being run by a coding agent, which races with Playwright's "wait for the server" check.
    // This opts back into the normal foreground server Playwright expects; it is a no-op outside
    // an agent environment.
    env: { ASTRO_PREVIEW_BACKGROUND: "1" },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
