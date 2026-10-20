import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// PHASE2B 4.10: the API behind the proxy is configurable (the accounts e2e runs its own API on :8001).
// Requests stay same-origin for the browser, so the session cookie and CSRF header just work.
const target = process.env.SP_API_TARGET || "http://127.0.0.1:8000";

const proxy = {
  "/api": {
    target,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
});
