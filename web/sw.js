// Offline shell: cache the app files, never the API.
const VERSION = 'farmiq-v2.0.0';
const SHELL = ['/', '/index.html', '/css/app.css', '/js/main.js', '/js/api.js', '/js/store.js', '/js/router.js', '/js/ui.js', '/js/three/scene.js',
  '/js/views/home.js', '/js/views/twin.js', '/js/views/intel.js', '/js/views/weather.js', '/js/views/scan.js', '/js/views/market.js', '/js/views/advisor.js', '/js/views/community.js',
  '/assets/logo.svg', '/manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) return;
  if (url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then((res) => { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(e.request, copy)); return res; })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match('/index.html'))),
  );
});
