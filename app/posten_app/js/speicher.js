// Lokaler Speicher in IndexedDB (über idb).
//
// Hier liegen ausschließlich Startnummern, Item-IDs und Postendaten –
// niemals Namen von Kindern (Spezifikation 4.2).
//
// Jede Erfassung ist geschrieben (Transaktion abgeschlossen), bevor die
// Oberfläche irgendeine Rückmeldung gibt (Spezifikation 4.3).

import { openDB } from "../vendor/idb.js";

const DB_NAME = "fahrradpruefung";
const DB_VERSION = 1;

let dbPromise;

function db() {
  dbPromise ??= openDB(DB_NAME, DB_VERSION, {
    upgrade(d) {
      d.createObjectStore("konfig");
      d.createObjectStore("zustand");
      const ev = d.createObjectStore("ereignisse", { keyPath: "event_id" });
      ev.createIndex("uebertragen", "uebertragen");
    },
  });
  return dbPromise;
}

export async function konfigLesen() {
  return (await db()).get("konfig", "aktuell");
}

export async function konfigSchreiben(konfig) {
  await (await db()).put("konfig", konfig, "aktuell");
}

export async function zustandLesen(schluessel, standard = undefined) {
  const wert = await (await db()).get("zustand", schluessel);
  return wert === undefined ? standard : wert;
}

export async function zustandSchreiben(schluessel, wert) {
  await (await db()).put("zustand", wert, schluessel);
}

export async function ereignisSpeichern(ereignis) {
  const tx = (await db()).transaction("ereignisse", "readwrite");
  await Promise.all([tx.store.add(ereignis), tx.done]);
}

export async function alleEreignisse() {
  return (await db()).getAll("ereignisse");
}

// uebertragen: 0 = noch offen, 1 = vom Server bestätigt, 2 = vom Server abgewiesen
export const OFFEN = 0;
export const UEBERTRAGEN = 1;
export const ABGEWIESEN = 2;

export async function anzahlNichtUebertragen() {
  return (await db()).countFromIndex("ereignisse", "uebertragen", OFFEN);
}

export async function anzahlAbgewiesen() {
  return (await db()).countFromIndex("ereignisse", "uebertragen", ABGEWIESEN);
}

export async function nichtUebertragene(hoechstens) {
  return (await db()).getAllFromIndex("ereignisse", "uebertragen", OFFEN, hoechstens);
}

// Erst nach Bestätigung durch den Server aufrufen (Spezifikation 4.4).
export async function markieren(eventIds, wert, grund = undefined) {
  if (!eventIds.length) return;
  const tx = (await db()).transaction("ereignisse", "readwrite");
  for (const id of eventIds) {
    const e = await tx.store.get(id);
    if (!e) continue;
    e.uebertragen = wert;
    if (grund) e.grund = grund[id];
    await tx.store.put(e);
  }
  await tx.done;
}

export async function allesLoeschen() {
  const d = await db();
  const tx = d.transaction(["konfig", "zustand", "ereignisse"], "readwrite");
  await Promise.all([
    tx.objectStore("konfig").clear(),
    tx.objectStore("zustand").clear(),
    tx.objectStore("ereignisse").clear(),
    tx.done,
  ]);
}

// Bittet den Browser, die Daten nicht bei Speicherknappheit zu verwerfen.
export async function dauerhaftAnfordern() {
  try {
    if (navigator.storage?.persisted && (await navigator.storage.persisted())) return true;
    return (await navigator.storage?.persist?.()) ?? false;
  } catch {
    return false;
  }
}
