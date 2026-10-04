import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import App from "./App"
import { ThemeProvider } from "./components/theme-provider"
import { I18nProvider } from "./i18n/provider"
import "@fontsource-variable/figtree"
import "@fontsource-variable/fraunces/full.css"
import "./index.css"

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

const root = document.getElementById("root")
if (!root) throw new Error("index.html has no #root element")

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ThemeProvider>
    </I18nProvider>
  </StrictMode>,
)
