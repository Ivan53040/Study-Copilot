import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on :8765 (same port the packaged app spawns). We proxy API
// calls so the frontend can use relative paths (no CORS juggling) in dev.
// Set STUDY_COPILOT_API to point the dev proxy at another port (e.g. when 8765
// is taken by a different program); scripts/restart_dev.cmd does this.
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
