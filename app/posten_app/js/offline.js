// Service Worker registrieren und prüfen, ob die App offline vollständig bereitsteht.

function nachricht(sw, daten, zeitlimitMs = 20_000) {
  return new Promise((ok) => {
    const kanal = new MessageChannel();
    const timer = setTimeout(() => ok({ bereit: false, ok: false, fehler: "Zeitüberschreitung" }), zeitlimitMs);
    kanal.port1.onmessage = (e) => {
      clearTimeout(timer);
      ok(e.data);
    };
    sw.postMessage(daten, [kanal.port2]);
  });
}

// Ergebnis: { bereit: true } oder { bereit: false, grund }
export async function offlineEinrichten() {
  if (!("serviceWorker" in navigator)) {
    return { bereit: false, grund: "Dieser Browser kann die App nicht offline speichern (keine sichere Verbindung?)." };
  }
  try {
    await navigator.serviceWorker.register("/p/sw.js", { scope: "/p/" });
    const reg = await navigator.serviceWorker.ready;
    const pfad = location.pathname;
    await nachricht(reg.active, { typ: "seite-speichern", pfad });
    const ergebnis = await nachricht(reg.active, { typ: "offline-bereit", pfad });
    return ergebnis.bereit ? { bereit: true } : { bereit: false, grund: "Noch nicht alle Teile gespeichert." };
  } catch (err) {
    console.error("Service Worker", err);
    return { bereit: false, grund: "Offline-Speicherung fehlgeschlagen." };
  }
}
