// Service Worker — Cache shell for offline support
const CACHE_NAME = "stock-hunter-v1";
const SHELL = ["/app/", "/app/index.html", "/app/manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // API calls — network only
  if (e.request.url.includes("/api/")) {
    e.respondWith(fetch(e.request));
    return;
  }
  // Shell — cache first
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});
