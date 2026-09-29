import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the API calls are proxied to a manually started backend (default
// :8765), so the frontend can use relative paths (no CORS juggling). Set
// STUDY_COPILOT_API to point the proxy elsewhere; scripts/restart_dev.cmd uses
// :8766 because 8765 is often taken by another program. (The packaged desktop
// app starts its own backend on 8768 or a free port and asks the shell for it.)
const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
const BACKEND = env?.STUDY_COPILOT_API || "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
