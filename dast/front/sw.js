const CACHE = 'resaleh-v4';
const STATIC = [
  '/',
  '/index.html',
  '/manifest.json',
  '/css/main.css',
  '/css/variables.css',
  '/css/components.css',
  '/css/responsive.css',
  '/js/app.js',
  '/js/api.js',
  '/js/chat.js',
  '/js/sidebar.js',
  '/js/admin.js',
  '/js/support.js',
  '/js/utils.js',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // API calls: always network
  if (e.request.url.includes('/api/') || e.request.url.includes(':8000')) return;

  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
