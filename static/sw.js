// electro Service Worker v1
// Estrategia: network-first con fallback a cache para HTML
// Cache-first para assets estaticos

const CACHE_NAME = 'electro-v1';
const CACHE_VERSION = '1';
const MAX_CACHE_AGE_DAYS = 30;

// Assets que se precargan al instalar el SW
const PRECACHE_URLS = [
  '/',
  '/login',
  '/static/css/tokens.css?v=2',
  '/static/css/base.css?v=2',
  '/static/css/components.css?v=2',
  '/static/css/menu.css?v=2',
  '/static/css/modal.css?v=3',
  '/static/css/padron.css?v=6',
  '/static/css/cobranza.css?v=1',
  '/static/css/tarifas.css?v=1',
  '/static/css/reportes.css?v=1',
  '/static/css/wizard.css?v=3',
  '/static/css/pwa.css?v=1',
  '/static/js/htmx.min.js?v=2',
  '/static/js/_hyperscript.min.js?v=0.9.13',
  '/static/js/theme.js?v=2',
  '/static/js/modal.js?v=3',
  '/static/js/kebab_close.js?v=2',
  '/static/js/connection.js?v=2',
  '/static/js/connection_mode.js?v=1',
  '/static/js/indexeddb.js?v=1',
  '/static/js/pwa_install.js?v=1',
  '/static/img/favicon.svg',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
];

// Instalacion
self.addEventListener('install', (event) => {
  console.log('[SW] Install v' + CACHE_VERSION);
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn('[SW] Some precache URLs failed:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activacion - limpiar caches viejos
self.addEventListener('activate', (event) => {
  console.log('[SW] Activate v' + CACHE_VERSION);
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
      );
    })
  );
  self.clients.claim();
});

// Fetch - estrategia diferenciada por tipo
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Solo manejamos GET
  if (req.method !== 'GET') return;

  // No cachear /api, /healthz, /static/sw.js, /sw.js
  if (url.pathname.startsWith('/api/') ||
      url.pathname === '/healthz' ||
      url.pathname === '/sw.js' ||
      url.pathname === '/static/sw.js') {
    return;
  }

  // Estrategia: network-first con fallback a cache
  event.respondWith(
    fetch(req)
      .then((response) => {
        // Cachear respuestas validas
        if (response && response.status === 200 && response.type === 'basic') {
          const respClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(req, respClone);
          });
        }
        return response;
      })
      .catch(() => {
        // Sin red: servir desde cache
        return caches.match(req).then((cached) => {
          if (cached) return cached;
          // Si no esta en cache, retornar pagina offline simple
          const accept = req.headers.get('accept') || '';
          if (accept.includes('text/html')) {
            return caches.match('/');
          }
          // Para otros recursos, fallar
          return new Response('Offline', { status: 503 });
        });
      })
  );
});

// Mensajes del cliente
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    caches.delete(CACHE_NAME).then(() => {
      event.ports[0].postMessage({ ok: true });
    });
  }
});
