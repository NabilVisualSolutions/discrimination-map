import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Dev server proxies the API + the server-rendered content routes to the
// running FastAPI backend (run-dev.sh, port 8020). Production build goes to
// web/dist, which FastAPI serves as the SPA shell (see REWRITE-PLAN.md §2).
export default defineConfig({
  // FastAPI mounts frontend/ at /static, so every built URL (JS chunks, CSS,
  // self-hosted font files) must start with /static/.
  base: "/static/",
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": { target: "http://127.0.0.1:8020", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
})
