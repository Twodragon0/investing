// Service Worker for Investing Dragon - Reports page offline cache
var CACHE_NAME = 'invest-dragon-v4';
var FONTS_CACHE = 'fonts-v1';
var IMAGES_CACHE = 'images-v1';
var IMAGES_CACHE_LIMIT = 200;

var CACHE_URLS = [
  '/reports/',
  '/assets/css/style.css',
  '/assets/js/reports.js',
  '/assets/js/core.js',
  '/assets/js/search.js'
];

var KNOWN_CACHES = [CACHE_NAME, FONTS_CACHE, IMAGES_CACHE];

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
        names.filter(function(n) { return KNOWN_CACHES.indexOf(n) === -1; })
             .map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

// Trim an image cache to IMAGES_CACHE_LIMIT entries (LRU: delete oldest keys first)
function trimImagesCache(cache) {
  return cache.keys().then(function(keys) {
    if (keys.length <= IMAGES_CACHE_LIMIT) return;
    var excess = keys.slice(0, keys.length - IMAGES_CACHE_LIMIT);
    return Promise.all(excess.map(function(req) { return cache.delete(req); }));
  });
}

self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);

  // Skip cross-origin requests (Google Fonts, CDNs, analytics) to avoid CSP issues
  if (url.origin !== self.location.origin) {
    return;
  }

  var pathname = url.pathname;

  // Cache-First: self-hosted fonts (woff2)
  if (pathname.startsWith('/assets/fonts/') && pathname.endsWith('.woff2')) {
    event.respondWith(
      caches.open(FONTS_CACHE).then(function(cache) {
        return cache.match(event.request).then(function(cached) {
          if (cached) return cached;
          return fetch(event.request).then(function(response) {
            if (response.ok) {
              cache.put(event.request, response.clone());
            }
            return response;
          });
        });
      })
    );
    return;
  }

  // Cache-First with LRU limit: generated images (avif, webp)
  if (pathname.startsWith('/assets/images/generated/') &&
      (pathname.endsWith('.avif') || pathname.endsWith('.webp'))) {
    event.respondWith(
      caches.open(IMAGES_CACHE).then(function(cache) {
        return cache.match(event.request).then(function(cached) {
          if (cached) return cached;
          return fetch(event.request).then(function(response) {
            if (response.ok) {
              cache.put(event.request, response.clone());
              trimImagesCache(cache);
            }
            return response;
          });
        });
      })
    );
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
    // Cache first for assets (CSS, JS)
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        return cached || fetch(event.request).then(function(response) {
          if (response.ok && (pathname.endsWith('.css') || pathname.endsWith('.js'))) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, responseClone); });
          }
          return response;
        });
      })
    );
  }
});
