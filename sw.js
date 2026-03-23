// Service Worker for Investing Dragon - Reports page offline cache
var CACHE_NAME = 'invest-dragon-v4';
var CACHE_URLS = [
  '/reports/',
  '/assets/css/style.css',
  '/assets/js/reports.js',
  '/assets/js/core.js',
  '/assets/js/search.js'
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(CACHE_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
             .map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Skip cross-origin requests (Google Fonts, CDNs, analytics) to avoid CSP issues
  if (url.origin !== self.location.origin) {
    return;
  }

  // Network-first for HTML pages, cache-first for static assets
  var isPage = event.request.mode === 'navigate' ||
               (event.request.method === 'GET' && event.request.headers.get('accept').indexOf('text/html') !== -1);

  if (isPage) {
    // Network first, fallback to cache
    event.respondWith(
      fetch(event.request).then(function(response) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, clone); });
        return response;
      }).catch(function() {
        return caches.match(event.request);
      })
    );
  } else {
    // Cache first for assets (CSS, JS, fonts)
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          if (response.ok && (url.pathname.endsWith('.css') || url.pathname.endsWith('.js'))) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, responseClone); });
          }
          return response;
        });
      })
    );
  }
});
