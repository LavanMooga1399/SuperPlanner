import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
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

/** Public files that belong to the app shell (copied as they are, so not part of the bundle). */
const PUBLIC_SHELL = ["/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png", "/icons/badge-72.png"];

/**
 * M6 2: the hand-written service worker `pwa/sw.js`, served as `/sw.js`. The build fills in the shell file list
 * (every emitted file except source maps, plus the public shell files) and a version hash of that list, so a new
 * build installs a new cache and drops the old one. The dev server serves it with an empty list (no caching).
 */
function serviceWorker(): Plugin {
  const template = () => readFileSync(fileURLToPath(new URL("./pwa/sw.js", import.meta.url)), "utf8");
  const fill = (version: string, shell: string[]) =>
    template().replace('"__SP_SW_VERSION__"', JSON.stringify(version)).replace("__SP_SW_SHELL__", JSON.stringify(shell));
  return {
    name: "sp-service-worker",
    // after Vite's HTML plugin, so `index.html` (the offline navigation fallback) is in the bundle
    enforce: "post",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if ((req.url ?? "").split("?")[0] !== "/sw.js") return next();
        res.setHeader("Content-Type", "text/javascript; charset=utf-8");
        res.setHeader("Cache-Control", "no-cache");
        res.end(fill("dev", []));
      });
    },
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
      const files = Object.keys(bundle)
        .filter((f) => !f.endsWith(".map") && f !== "sw.js")
        .map((f) => `/${f}`)
        .sort();
      const shell = [...files, ...PUBLIC_SHELL];
      const hash = createHash("sha256");
      for (const f of files) {
        const chunk = bundle[f.slice(1)];
        hash.update(f);
        hash.update(chunk.type === "chunk" ? chunk.code : typeof chunk.source === "string" ? chunk.source : Buffer.from(chunk.source));
      }
      if (!shell.includes("/index.html")) throw new Error("sp-service-worker: index.html missing from the bundle");
      this.emitFile({ type: "asset", fileName: "sw.js", source: fill(hash.digest("hex").slice(0, 16), shell) });
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), serviceWorker()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
});
