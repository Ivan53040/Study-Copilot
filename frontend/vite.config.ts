import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on :8765 (same port the packaged app spawns). We proxy API
// calls so the frontend can use relative paths (no CORS juggling) in dev.
const BACKEND = "http://127.0.0.1:8765";

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
