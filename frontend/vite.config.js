import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// The backend runs on :8000. We proxy API calls so the frontend can use
// relative paths (no CORS juggling) in dev. Change here if your port differs.
var BACKEND = "http://127.0.0.1:8000";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": {
                target: BACKEND,
                changeOrigin: true,
                rewrite: function (path) { return path.replace(/^\/api/, ""); },
            },
        },
    },
});
