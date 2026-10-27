// Fest verdrahtete Beispieldaten für den Prototyp (Schritt 2).
// Entspricht der Antwort von GET /api/p/{token}/config – ohne Namen.

export const BEISPIEL_KONFIG = {
  lauf_id: 1,
  datum: "2026-10-20",
  posten: { id: 3, name: "Posten 3 – Einmündung Lindenweg" },
  items: [
    { id: 11, kurzbezeichnung: "Schulterblick", position: 1 },
    { id: 12, kurzbezeichnung: "Handzeichen", position: 2 },
    { id: 13, kurzbezeichnung: "Einordnen", position: 3 },
    { id: 14, kurzbezeichnung: "Gegenverkehr beachten", position: 4 },
    { id: 15, kurzbezeichnung: "Bremsbereitschaft", position: 5 },
  ],
  startnummern: Array.from({ length: 24 }, (_, i) => i + 1),
};
