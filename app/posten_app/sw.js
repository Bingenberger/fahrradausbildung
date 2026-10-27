// Service Worker der Posten-App (Spezifikation 4.3).
//
// __VERSION__ und __ASSETS__ setzt der Server beim Ausliefern ein
// (app/posten/seiten.py): Die Version ist ein Hash über alle App-Dateien.
//
// Strategie:
//   /p/assets/…   Cache zuerst (vorab beim Installieren gespeichert)
//   /p/{token}    Cache zuerst; die Seite speichert sich selbst nach dem Einrichten
//   /api/…        nie aus dem Cache – Erfassungen dürfen nicht „verschluckt" werden

const VERSION = "__VERSION__";
const CACHE = `posten-${VERSION}`;
const ASSETS = __ASSETS__;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Seiten aus der alten Version mitnehmen, damit ein Update offline nichts zerstört.
      const namen = await caches.keys();
      const neu = await caches.open(CACHE);
      for (const name of namen) {
        if (name === CACHE || !name.startsWith("posten-")) continue;
        const alt = await caches.open(name);
        for (const anfrage of await alt.keys()) {
          const pfad = new URL(anfrage.url).pathname;
          if (!pfad.startsWith("/p/assets/") && !(await neu.match(pfad))) {
            await neu.put(pfad, await alt.match(anfrage));
          }
        }
        await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

const SEITE = /^\/p\/[A-Za-z0-9_-]+$/;

async function seiteAusCache(anfrage) {
  const pfad = new URL(anfrage.url).pathname;
  const cache = await caches.open(CACHE);
  const treffer = await cache.match(pfad);
  if (treffer) return treffer;
  try {
    const antwort = await fetch(anfrage);
    if (antwort.ok) await cache.put(pfad, antwort.clone());
    return antwort;
  } catch (err) {
    // Offline und diese Posten-Seite nie geladen (z. B. iPad soll den Posten wechseln):
    // Die Hülle ist für alle Tokens gleich – die App erklärt dann selbst, was zu tun ist.
    for (const k of await cache.keys()) {
      if (SEITE.test(new URL(k.url).pathname)) return cache.match(k);
    }
    throw err;
  }
}

async function assetAusCache(anfrage) {
  const cache = await caches.open(CACHE);
  const treffer = await cache.match(anfrage, { ignoreSearch: true });
  if (treffer) return treffer;
  const antwort = await fetch(anfrage);
  if (antwort.ok) await cache.put(anfrage, antwort.clone());
  return antwort;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return; // immer Netz
  if (url.pathname.startsWith("/p/assets/")) {
    event.respondWith(assetAusCache(event.request));
  } else if (event.request.mode === "navigate" && SEITE.test(url.pathname)) {
    event.respondWith(seiteAusCache(event.request));
  }
});

// Die Seite bittet nach dem Einrichten: „speichere mich" und „bin ich offline bereit?"
self.addEventListener("message", (event) => {
  const { typ, pfad } = event.data || {};
  const antworten = (wert) => event.ports[0]?.postMessage(wert);
  if (typ === "seite-speichern") {
    event.waitUntil(
      (async () => {
        try {
          const cache = await caches.open(CACHE);
          await cache.add(pfad);
          antworten({ ok: true });
        } catch (err) {
          antworten({ ok: false, fehler: String(err) });
        }
      })(),
    );
  } else if (typ === "offline-bereit") {
    event.waitUntil(
      (async () => {
        const cache = await caches.open(CACHE);
        const alle = [...ASSETS, pfad];
        const fehlend = [];
        for (const p of alle) if (!(await cache.match(p))) fehlend.push(p);
        antworten({ bereit: fehlend.length === 0, version: VERSION, fehlend: fehlend.length });
      })(),
    );
  }
});
