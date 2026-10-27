// Reine Erfassungslogik – kein DOM, keine Speicherzugriffe.
//
// Ein Ereignis sieht lokal so aus wie auf dem Server:
//   { event_id, typ, startnummer, nutzlast, erfasst_am, uebertragen }
//
// Durchgänge werden pro Kind gezählt, nicht global: Kinder überholen sich,
// machen Pause oder werden übersprungen. Der Schlüssel (startnummer, durchgang_nr)
// bleibt so für jede tatsächliche Vorbeifahrt eindeutig.
//
// Rückgängig erzeugt ein Storno-Ereignis mit demselben Schlüssel
// ({ durchgang_nr, fehlende_items: [], storniert: true }). Wird das Kind danach
// erneut erfasst, bekommt es wieder dieselbe durchgang_nr und das jüngere
// Ereignis gewinnt.

export const STUFEN = [
  { stufe: 1, text: "sicher", symbol: "✓" },
  { stufe: 2, text: "teilweise sicher", symbol: "~" },
  { stufe: 3, text: "unsicher", symbol: "!" },
];

// UUIDv4 über crypto.getRandomValues – funktioniert anders als
// crypto.randomUUID() auch außerhalb sicherer Kontexte (z. B. Test im LAN per http).
export function neueEventId() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function juenger(a, b) {
  // Eindeutige Reihenfolge auch bei gleichem Zeitstempel.
  if (a.erfasst_am !== b.erfasst_am) return a.erfasst_am > b.erfasst_am;
  return a.event_id > b.event_id;
}

// Jüngstes Durchgangs-Ereignis je (startnummer, durchgang_nr).
export function durchgaengeJeSchluessel(ereignisse) {
  const m = new Map();
  for (const e of ereignisse) {
    if (e.typ !== "durchgang") continue;
    const k = `${e.startnummer}|${e.nutzlast.durchgang_nr}`;
    const bisher = m.get(k);
    if (!bisher || juenger(e, bisher)) m.set(k, e);
  }
  return m;
}

// Startnummer -> sortierte Liste der gültigen (nicht stornierten) durchgang_nr.
export function gueltigeDurchgaenge(ereignisse) {
  const m = new Map();
  for (const e of durchgaengeJeSchluessel(ereignisse).values()) {
    if (e.nutzlast.storniert) continue;
    if (!m.has(e.startnummer)) m.set(e.startnummer, []);
    m.get(e.startnummer).push(e.nutzlast.durchgang_nr);
  }
  for (const liste of m.values()) liste.sort((a, b) => a - b);
  return m;
}

export function naechsteDurchgangNr(ereignisse, startnummer) {
  const liste = gueltigeDurchgaenge(ereignisse).get(startnummer) ?? [];
  return liste.length ? liste[liste.length - 1] + 1 : 1;
}

export function naechsteNummer(startnummern, aktuell) {
  const i = startnummern.indexOf(aktuell);
  return startnummern[(i + 1) % startnummern.length];
}

// Startnummer -> jüngstes Sicherheits-Ereignis.
export function sicherheitJeNummer(ereignisse) {
  const m = new Map();
  for (const e of ereignisse) {
    if (e.typ !== "sicherheit") continue;
    const bisher = m.get(e.startnummer);
    if (!bisher || juenger(e, bisher)) m.set(e.startnummer, e);
  }
  return m;
}

function ereignis(typ, startnummer, nutzlast) {
  return {
    event_id: neueEventId(),
    typ,
    startnummer,
    nutzlast,
    erfasst_am: new Date().toISOString(),
    uebertragen: 0,
  };
}

export function durchgangsEreignis(startnummer, durchgang_nr, fehlende_items) {
  return ereignis("durchgang", startnummer, { durchgang_nr, fehlende_items: [...fehlende_items] });
}

export function stornoEreignis(startnummer, durchgang_nr) {
  return ereignis("durchgang", startnummer, { durchgang_nr, fehlende_items: [], storniert: true });
}

export function sicherheitsEreignis(startnummer, stufe, bemerkung) {
  const nutzlast = { stufe };
  if (bemerkung) nutzlast.bemerkung = bemerkung;
  return ereignis("sicherheit", startnummer, nutzlast);
}
