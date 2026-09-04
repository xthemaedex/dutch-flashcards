/* sw.js — service worker: offline app shell + static data + daily reminder.
 * scripts/build_static.py --deploy bumps CACHE so a redeploy refreshes clients. */
const CACHE = "dfx-v14";
const SHELL = [
  "/", "/index.html", "/app.css", "/app.js", "/srs.js",
  "/manifest.webmanifest",
  "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png",
  "/apple-touch-icon.png", "/favicon.png",
];
// static data the app can't run without — precached so a cold offline start works
// (best-effort: a failure here must not abort the install)
const DATA = ["/data/cards.json", "/data/details.json", "/data/sets.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) =>
      c.addAll(SHELL).then(() =>
        Promise.all(DATA.map(async (u) => {
          try {
            const r = await fetch(u);           // hits the edge cache, not Turso
            if (r.ok) return c.put(u, r);
          } catch (_) { /* offline / API down */ }
          // carry the last-known-good copy forward from a previous cache so a
          // version bump never leaves the app with no data to run on
          const old = await caches.match(u);
          if (old) return c.put(u, old);
        }))
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

/* --- fetch strategy: cache-first for everything same-origin ---
 * The whole app is static (shell + /data/*.json). New content ships as a new
 * deploy, which changes sw.js (build_static.py bumps CACHE), which re-runs
 * install and refreshes the DATA files. So a plain cache-first is safe. */
function cacheFirst(req) {
  return caches.match(req).then((hit) =>
    hit || fetch(req).then((res) => {
      if (res.ok || res.type === "opaque") {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy).catch(() => {}));
      }
      return res;
    })
  );
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Cross-origin (jsDelivr audio + images): leave to the browser's native
  // loader — routing opaque/range media through the SW stalls playback.
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }
  // same-origin /audio/ and /img/ only exist in local dev; range requests bypass
  if (url.pathname.startsWith("/audio/") && req.headers.has("range")) return;

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
