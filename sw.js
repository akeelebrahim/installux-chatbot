/* Installux ChatBot PWA Service Worker */
const CACHE_NAME = "installux-chatbot-v2";
const PRECACHE_URLS = [
  "/",
  "/manifest.json",
  "/logo.png"
];

// Install event: cache essential assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.error("Precache failed:", err);
      });
    })
  );
  self.skipWaiting();
});

// Activate event: clean up old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch event: serve from cache, fallback to network
self.addEventListener("fetch", (event) => {
  // Skip non-GET requests
  if (event.request.method !== "GET") return;

  // Skip API calls to external domains (let network handle them)
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin && !url.pathname.startsWith("/api/")) return;

  // For /api/ routes, try network first (they may be Netlify Functions)
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache successful API responses
          if (response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, copy);
            });
          }
          return response;
        })
        .catch(() => {
          // Fallback to cache if network fails
          return caches.match(event.request).then((cached) => cached || response);
        })
    );

  // For all other requests, use cache-first strategy
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) return cachedResponse;

      return fetch(event.request).then((networkResponse) => {
        // Cache index.html for navigation baseline
        if (event.request.url.endsWith("index.html") || event.request.url === "/") {
          const copy = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, copy);
          });
        }
        return networkResponse;
      });
    })
  );
});