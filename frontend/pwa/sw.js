/*
 * SuperPlanner service worker (docs/M6-DESIGN.md 2), hand-written, no libraries. Built by the `sp-service-worker`
 * plugin in vite.config.ts, which replaces the two placeholders below with the build's file list and its hash.
 *
 * - App shell: the built files are pre-cached per version on install; old versions are dropped on activate.
 *   Navigations are network-first with the cached `index.html` as the offline fallback; shell files cache-first.
 * - API (`/api/`): never cached and never answered from a cache (network only). The only offline data is the last
 *   mobile home snapshot, which the page itself keeps in IndexedDB (src/mfg/mobile/snapshot.ts).
 * - Push: shows the notification (title, short body, link path only) and opens / focuses the app at that path.
 * - Dev server: the file list is empty, so nothing is cached and fetches are not intercepted.
 */
/* eslint-disable no-restricted-globals */
const VERSION = "__SP_SW_VERSION__";
const SHELL = __SP_SW_SHELL__;
const CACHE = `sp-shell-${VERSION}`;
const SHELL_SET = new Set(SHELL);

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      if (SHELL.length) {
        const cache = await caches.open(CACHE);
        await cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload" })));
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith("sp-shell-") && k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "version" && event.ports && event.ports[0]) event.ports[0].postMessage({ version: VERSION, shell: SHELL.length });
});

// dev server (empty shell): no fetch handler at all, so requests are never routed through the worker
if (SHELL.length) self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // API: network only, never cached
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch (e) {
          const cached = await caches.match("/index.html", { cacheName: CACHE });
          if (cached) return cached;
          throw e;
        }
      })(),
    );
    return;
  }
  if (SHELL_SET.has(url.pathname)) {
    event.respondWith(
      (async () => {
        const cached = await caches.match(url.pathname, { cacheName: CACHE });
        return cached || fetch(req);
      })(),
    );
  }
});

/** Only same-origin app paths are opened (the payload carries a path, never a URL). */
function safePath(link) {
  if (typeof link !== "string" || !link.startsWith("/") || link.startsWith("//") || link.includes("\\")) return "/m";
  return link;
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "SuperPlanner", body: event.data ? event.data.text() : "" };
  }
  const title = typeof data.title === "string" && data.title ? data.title.slice(0, 120) : "SuperPlanner";
  const body = typeof data.body === "string" ? data.body.slice(0, 240) : "";
  const link = safePath(data.link);
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag: typeof data.tag === "string" ? data.tag : undefined,
      data: { link, topic: typeof data.topic === "string" ? data.topic : null },
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      requireInteraction: data.urgency === "high" || data.topic === "critical_alerts",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = safePath(event.notification.data && event.notification.data.link);
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const c of all) {
        if (new URL(c.url).origin === self.location.origin && "focus" in c) {
          await c.focus();
          if ("navigate" in c) {
            try {
              await c.navigate(link);
            } catch (e) {
              c.postMessage({ type: "open", link });
            }
          }
          return;
        }
      }
      await self.clients.openWindow(link);
    })(),
  );
});
