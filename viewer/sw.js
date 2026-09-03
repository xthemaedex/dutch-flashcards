/* sw.js — service worker: offline app shell + data/audio caching + daily reminder.
 * Bump CACHE on any shell change to force an update. */
const CACHE = "dfx-v7";
const SHELL = [
  "/", "/index.html", "/app.css", "/app.js", "/srs.js",
  "/manifest.webmanifest",
  "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png",
  "/apple-touch-icon.png", "/favicon.png",
];
// data the app can't run without — precached so a cold offline start works
// (best-effort: a failure here must not abort the install)
const DATA = ["/api/cards", "/api/details", "/api/sets", "/api/images"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      c.addAll(SHELL).then(() =>
        Promise.all(DATA.map((u) =>
          fetch(u).then((r) => r.ok && c.put(u, r)).catch(() => {})))
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* --- fetch strategies --- */
function cacheFirst(req) {
  return caches.match(req).then((hit) =>
    hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })
  );
}
function staleWhileRevalidate(req) {
  return caches.open(CACHE).then((c) =>
    c.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res.ok) c.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }
  if (url.pathname.startsWith("/audio/") ||
      url.pathname.startsWith("/img/") ||
      url.pathname.startsWith("/api/word/")) {
    e.respondWith(cacheFirst(req));
    return;
  }
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(staleWhileRevalidate(req));
    return;
  }
  e.respondWith(cacheFirst(req));
});

/* --- daily reminder ---
 * The page writes { due, notified } into IndexedDB (dfx/meta/reminder). We can't
 * read the page's localStorage from here, so IndexedDB is the bridge. */
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open("dfx", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("meta");
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
function idbGet(key) {
  return idb().then((db) => new Promise((res) => {
    const tx = db.transaction("meta", "readonly").objectStore("meta").get(key);
    tx.onsuccess = () => res(tx.result);
    tx.onerror = () => res(null);
  }));
}
function idbSet(key, val) {
  return idb().then((db) => new Promise((res) => {
    const tx = db.transaction("meta", "readwrite");
    tx.objectStore("meta").put(val, key);
    tx.oncomplete = () => res();
  }));
}

function maybeNotify(force) {
  const today = new Date().toLocaleDateString("sv");
  return idbGet("reminder").then((m) => {
    m = m || { due: 0, notified: null };
    if (!force) {
      if (m.notified === today) return;      // already nudged today
      if (!(m.due > 0)) return;              // nothing due
    }
    const body = m.due > 0
      ? `You have ${m.due} card${m.due === 1 ? "" : "s"} due for review.`
      : "Time for today's Dutch review.";
    return self.registration.showNotification("Dutch Flashcards", {
      body,
      tag: "dutch-daily-reminder",
      icon: "/icon-192.png",
      badge: "/favicon.png",
      data: { url: "/?tab=review" },
    }).then(() => idbSet("reminder", Object.assign(m, { notified: today })));
  });
}

self.addEventListener("periodicsync", (e) => {
  if (e.tag === "dutch-daily-reminder") e.waitUntil(maybeNotify(false));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) if ("focus" in w) return w.focus();
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener("message", (e) => {
  if (e.data === "skip-waiting") self.skipWaiting();
  if (e.data === "test-notification") e.waitUntil(maybeNotify(true));
});
