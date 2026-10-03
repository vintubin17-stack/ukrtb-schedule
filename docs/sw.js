/* ------------------------------------------------------------------
   Service worker статической версии.

   Зачем: ярлык на домашнем экране iPhone должен открываться всегда.
   Без service worker iOS при малейшем сбое сети показывает «Network lost»
   и ничего больше. С ним страница и расписание берутся из кэша, а сеть
   используется только для обновления данных.

   Регистрируется только в статической версии (в Flask-версии этот файл
   лежит в /static/ и получил бы неверную область действия).
   ------------------------------------------------------------------ */

var VERSION = 'ukrtb-v5';
var SHELL_CACHE = VERSION + '-shell';
var RUNTIME_CACHE = VERSION + '-runtime';

/* Оболочка приложения: всё, что нужно, чтобы страница открылась без сети. */
var SHELL_FILES = [
    './',
    'index.html',
    'app.js',
    'styles.css',
    'manifest.webmanifest',
    'icons/favicon.svg',
    'icons/icon-192.png',
    'icons/icon-512.png',
    'icons/apple-touch-icon.png',
    'install.html',
    'data.json'
];

/* Файл с расписанием: обновляем из сети, но без сети отдаём кэш. */
function isScheduleFile(pathname) {
    return pathname.slice(-10) === '/data.json' || pathname.slice(-9) === 'data.json';
}

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(SHELL_CACHE).then(function (cache) {
            // Каждый файл кладём отдельно: если один не скачался,
            // установка всё равно должна состояться.
            return Promise.all(SHELL_FILES.map(function (url) {
                return cache.add(new Request(url, { cache: 'reload' }))
                    .catch(function () { /* некритичный файл пропускаем */ });
            }));
        }).then(function () {
            return self.skipWaiting();
        })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.map(function (key) {
                if (key !== SHELL_CACHE && key !== RUNTIME_CACHE) {
                    return caches.delete(key);
                }
            }));
        }).then(function () {
            return self.clients.claim();
        })
    );
});

function networkFirst(request, cacheName) {
    return fetch(request).then(function (response) {
        if (response && response.ok) {
            var copy = response.clone();
            caches.open(cacheName).then(function (cache) { cache.put(request, copy); });
        }
        return response;
    }).catch(function () {
        return caches.match(request).then(function (cached) {
            return cached || caches.match('data.json');
        });
    });
}

function cacheFirst(request, cacheName) {
    return caches.match(request).then(function (cached) {
        if (cached) return cached;
        return fetch(request).then(function (response) {
            if (response && response.ok) {
                var copy = response.clone();
                caches.open(cacheName).then(function (cache) { cache.put(request, copy); });
            }
            return response;
        });
    });
}

function staleWhileRevalidate(request, cacheName) {
    return caches.open(cacheName).then(function (cache) {
        return cache.match(request).then(function (cached) {
            var network = fetch(request).then(function (response) {
                if (response && (response.ok || response.type === 'opaque')) {
                    cache.put(request, response.clone());
                }
                return response;
            }).catch(function () { return cached; });
            return cached || network;
        });
    });
}

self.addEventListener('fetch', function (event) {
    var request = event.request;
    if (request.method !== 'GET') return;

    var url;
    try {
        url = new URL(request.url);
    } catch (e) {
        return;
    }

    // Расписание: сначала сеть (чтобы «Обновить данные» работало),
    // без сети — из кэша.
    if (isScheduleFile(url.pathname)) {
        event.respondWith(networkFirst(request, SHELL_CACHE));
        return;
    }

    // Открытие страницы (в том числе из ярлыка): сначала кэш именно этой
    // страницы, потом сеть, и только в крайнем случае — главная.
    // Раньше здесь всегда отдавался index.html, из-за чего переход на
    // любую другую страницу (например, install.html) показывал главную.
    if (request.mode === 'navigate') {
        event.respondWith(
            caches.match(request, { ignoreSearch: true }).then(function (cached) {
                if (cached) return cached;
                return fetch(request).then(function (response) {
                    var copy = response.clone();
                    caches.open(SHELL_CACHE).then(function (cache) { cache.put(request, copy); });
                    return response;
                }).catch(function () {
                    return caches.match('index.html');
                });
            })
        );
        return;
    }

    if (url.origin === self.location.origin) {
        event.respondWith(cacheFirst(request, SHELL_CACHE));
        return;
    }

    // Сторонние ресурсы (например, Tailwind с CDN) — кэшируем на лету.
    event.respondWith(staleWhileRevalidate(request, RUNTIME_CACHE));
});
