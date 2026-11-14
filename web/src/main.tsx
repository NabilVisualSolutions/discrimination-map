import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import "./i18n"
import "@fontsource/fragment-mono/400.css"
import "@fontsource/fragment-mono/400-italic.css"
import "@fontsource/sora/600.css"
import "@fontsource/sora/700.css"
import "@fontsource/sora/800.css"
import "./theme.css"
import "./ui.css"
import { App } from "./App"
import { initAnalyticsIfConsented } from "./lib/analytics"

initAnalyticsIfConsented()

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </StrictMode>
)
