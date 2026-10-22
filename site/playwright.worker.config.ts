import { defineConfig } from "@playwright/test"

const PORT = Number(process.env.WORKER_E2E_PORT ?? 8788)

// Exercise the real Workers runtime and static asset binding, without a Cloudflare account.
export default defineConfig({
  testDir: "worker-e2e",
  use: { baseURL: `http://localhost:${PORT}` },
  webServer: {
    command: `pnpm exec wrangler dev --local --port ${PORT}`,
    url: `http://localhost:${PORT}`,
    env: { WRANGLER_SEND_METRICS: "false" },
  },
})
