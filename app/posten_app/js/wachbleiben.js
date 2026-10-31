// Display anlassen, solange am Posten erfasst wird.
//
// Das iPad liegt zwischen zwei Kindern still auf dem Tisch. Mit der üblichen
// automatischen Sperre nach zwei Minuten müsste die Aufsicht vor jedem Kind
// erst entsperren – genau in dem Moment, in dem sie auf den Verkehr schauen
// soll. Die Screen Wake Lock API hält den Bildschirm wach, solange die Seite
// sichtbar ist.
//
// Sie ersetzt die Geräteeinstellung nicht: „Einstellungen → Anzeige &
// Helligkeit → Automatische Sperre → Nie" (am besten per MDM-Profil) bleibt
// der verlässlichere Weg. Dieses Modul ist die Absicherung für Geräte, die
// nicht so eingerichtet wurden.
//
// Drei Eigenheiten, die hier abgefangen werden:
// - Das System gibt den Lock selbst frei, sobald die App in den Hintergrund
//   geht oder das Display von Hand gesperrt wird. Beim Zurückkommen muss er
//   neu angefordert werden – sonst ist er nach dem ersten Wegtippen still weg.
// - Im Energiesparmodus darf das Gerät die Anfrage ablehnen.
// - Vor iPadOS 16.4 gibt es die Schnittstelle gar nicht.
//
// Die Helligkeit selbst lässt sich aus dem Browser nicht steuern; das
// automatische Abdunkeln vor der Sperre entfällt mit dem Lock mit.

let sperre = null;
let gewollt = false;
let horcht = false;
let versucht_ = false;

/** Kann dieses Gerät das Display überhaupt wachhalten? */
export function unterstuetzt() {
  return Boolean(navigator.wakeLock);
}

/** Hält das Display gerade wirklich? */
export function aktiv() {
  return sperre !== null;
}

/** Wurde es schon versucht? Vorher sagt ``aktiv()`` nur „noch nicht gefragt". */
export function versucht() {
  return versucht_;
}

async function anfordern() {
  if (!gewollt || sperre || !unterstuetzt() || document.visibilityState !== "visible") return;
  try {
    sperre = await navigator.wakeLock.request("screen");
    // Beim Wegschalten gibt das System frei; dann hier aufräumen.
    sperre.addEventListener("release", () => {
      sperre = null;
    });
  } catch (fehler) {
    // Energiesparmodus, fehlende Berechtigung: kein Grund, die Erfassung zu
    // stören. Die Oberfläche fragt mit aktiv() nach und sagt es ruhig an.
    sperre = null;
  }
  versucht_ = true;
}

/**
 * Display wachhalten, bis ``loslassen()`` kommt. Mehrfach aufrufbar.
 * Liefert, ob es geklappt hat.
 */
export async function halten() {
  gewollt = true;
  if (!horcht) {
    document.addEventListener("visibilitychange", anfordern);
    horcht = true;
  }
  await anfordern();
  return aktiv();
}

/** Wieder der Geräteeinstellung überlassen – am Ende des Laufs. */
export async function loslassen() {
  gewollt = false;
  if (!sperre) return;
  try {
    await sperre.release();
  } catch (fehler) {
    // Schon freigegeben – nichts zu tun.
  }
  sperre = null;
}
