const CACHE_NAME = 'nutritrack-v2';

self.addEventListener('install', (event) => {
  // Pre-cache only non-HTML assets
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(['/manifest.json', '/icon.svg']))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Always network-first for API and HTML
  if (url.pathname.startsWith('/api/') || url.pathname === '/' || url.pathname.endsWith('.html')) {
    event.respondWith(fetch(event.request).catch(() =>
      url.pathname.startsWith('/api/')
        ? new Response(JSON.stringify({ error: 'Offline' }), { headers: { 'Content-Type': 'application/json' } })
        : caches.match('/index.html')
    ));
    return;
  }

  // Cache-first for icons and manifest only
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
