// Verbindung zum Server: Konfiguration, Upload, Status (Spezifikation 4.4, 6, 7).
//
// Der Upload ist idempotent: Der Server bestätigt jede gespeicherte event_id,
// auch wenn sie schon bei einem früheren (abgebrochenen) Versuch ankam. Erst
// diese Bestätigung markiert ein Ereignis lokal als übertragen.

import * as speicher from "./speicher.js";

const ZEITLIMIT_MS = 20_000;
const STAPEL = 500; // Server erlaubt bis 1000 je Anfrage

function api(token, pfad) {
  return `/api/p/${encodeURIComponent(token)}/${pfad}`;
}

async function abrufen(url, optionen = {}) {
  const abbruch = new AbortController();
  const timer = setTimeout(() => abbruch.abort(), ZEITLIMIT_MS);
  try {
    return await fetch(url, { ...optionen, signal: abbruch.signal, cache: "no-store", credentials: "omit" });
  } finally {
    clearTimeout(timer);
  }
}

// Ergebnis: { status: "ok", daten } | { status: "ungueltig" } | { status: "fehler" }
async function jsonHolen(url) {
  try {
    const r = await abrufen(url);
    if (r.status === 404) return { status: "ungueltig" };
    if (!r.ok) return { status: "fehler" };
    return { status: "ok", daten: await r.json() };
  } catch {
    return { status: "fehler" };
  }
}

export function konfigHolen(token) {
  return jsonHolen(api(token, "config"));
}

export function serverStatus(token) {
  return jsonHolen(api(token, "status"));
}

let laufend = null;

// Lädt alle offenen Ereignisse hoch. Läuft nie doppelt parallel.
export function hochladen(token) {
  laufend ??= hochladenIntern(token).finally(() => (laufend = null));
  return laufend;
}

async function hochladenIntern(token) {
  let akzeptiert = 0;
  let abgewiesen = 0;
  for (;;) {
    const offen = await speicher.nichtUebertragene(STAPEL);
    if (!offen.length) return { status: "ok", akzeptiert, abgewiesen };

    const events = offen.map(({ event_id, typ, startnummer, nutzlast, erfasst_am }) => ({
      event_id, typ, startnummer, nutzlast, erfasst_am,
    }));
    let antwort;
    try {
      antwort = await abrufen(api(token, "events"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
      });
    } catch {
      return { status: "fehler", akzeptiert, abgewiesen };
    }
    if (antwort.status === 404) return { status: "ungueltig", akzeptiert, abgewiesen };
    if (!antwort.ok) return { status: "fehler", akzeptiert, abgewiesen };

    let daten;
    try {
      daten = await antwort.json();
    } catch {
      return { status: "fehler", akzeptiert, abgewiesen };
    }
    const bestaetigt = new Set(daten.akzeptiert ?? []);
    const gruende = Object.fromEntries((daten.abgewiesen ?? []).filter((a) => a.event_id).map((a) => [a.event_id, a.grund]));
    // Was der Server weder bestätigt noch mit ID abgewiesen hat (z. B. unlesbar), gilt als abgewiesen,
    // sonst würde es endlos erneut gesendet.
    for (const e of offen) {
      if (!bestaetigt.has(e.event_id) && !(e.event_id in gruende)) gruende[e.event_id] = "unbekannt";
    }
    await speicher.markieren([...bestaetigt], speicher.UEBERTRAGEN);
    await speicher.markieren(Object.keys(gruende), speicher.ABGEWIESEN, gruende);
    akzeptiert += bestaetigt.size;
    abgewiesen += Object.keys(gruende).length;
  }
}
