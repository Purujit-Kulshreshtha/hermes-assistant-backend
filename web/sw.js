const CACHE = "nancy-shell-v5";
const ASSETS = [
  "/",
  "/styles.css",
  "/layout.css",
  "/voice.css",
  "/tts.css",
  "/app.js",
  "/voice.js",
  "/tts.js",
  "/tts-worker.js",
  "/manifest.webmanifest",
  "/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const path = url.pathname;
  if (
    url.origin !== self.location.origin ||
    event.request.method !== "GET" ||
    path.startsWith("/commands") ||
    path.startsWith("/history") ||
    path.startsWith("/settings")
  ) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
