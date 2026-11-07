// PIN-Sperre vor der Posten-App.
//
// Manche Schulen nutzen die iPads auch im Unterricht. Hat die Schule in der
// Verwaltung eine PIN gesetzt, fragt die App sie beim Öffnen ab – und wenn sie
// länger im Hintergrund war. Die PIN kommt mit der Konfiguration und liegt lokal,
// damit die Sperre auch offline greift. Sie schützt vor neugierigen Kindern,
// nicht vor Angreifern: Wer das iPad entsperrt, darf ohnehin erfassen.
//
// Nach mehreren Fehlversuchen wartet die Tastatur eine Weile. Die Wartezeit liegt
// in IndexedDB, damit Schließen und neu Öffnen sie nicht umgeht.

import * as speicher from "./speicher.js";

export const PIN_LAENGE = 4;
// Kurz weggeschaltet (Mitteilung, versehentlich Home-Taste) bleibt ohne PIN.
export const HINTERGRUND_FRIST_MS = 2 * 60_000;
export const MAX_FEHLVERSUCHE = 5;
export const WARTEZEIT_MS = 30_000;

const $ = (id) => document.getElementById(id);

let pin = null;
let eingabe = "";
let fehlversuche = 0;
let gesperrtBis = 0;
let warteTimer = null;
let verstecktSeit = null;

export function gueltigePin(wert) {
  return typeof wert === "string" && new RegExp(`^[0-9]{${PIN_LAENGE}}$`).test(wert);
}

// Die Sperre baut sich selbst auf, statt im HTML zu stehen: Nach einem Update kann
// das iPad kurz eine ältere zwischengespeicherte Seite mit neuem Skript zeigen –
// die Sperre muss trotzdem greifen.
function aufbauen() {
  if ($("sperre")) return;
  const el = (tag, klasse, id, text) => {
    const e = document.createElement(tag);
    if (klasse) e.className = klasse;
    if (id) e.id = id;
    if (text) e.textContent = text;
    return e;
  };
  const huelle = el("div", "sperre", "sperre");
  huelle.hidden = true;
  huelle.setAttribute("role", "dialog");
  huelle.setAttribute("aria-modal", "true");
  huelle.setAttribute("aria-labelledby", "sperre-titel");
  const inhalt = el("div", "sperre-inhalt");
  const punkte = el("div", "sperre-punkte", "sperre-punkte");
  punkte.setAttribute("role", "status");
  const meldung = el("p", "sperre-meldung", "sperre-meldung");
  meldung.setAttribute("aria-live", "polite");
  inhalt.append(
    el("h1", "", "sperre-titel", "PIN eingeben"),
    el("p", "sperre-posten", "sperre-posten"),
    punkte,
    meldung,
    el("div", "sperre-tasten", "sperre-tasten"),
    el("p", "sperre-hilfe", "", "PIN vergessen? Die Lehrkraft findet sie in der Verwaltung unter „Konto“."),
  );
  huelle.append(inhalt);
  document.body.append(huelle);
}

// Einmal beim Start: Sperre aufbauen und auf Hintergrund achten.
// ``neuePin`` null oder ungültig: keine Sperre.
export async function einrichten(neuePin, postenName = "") {
  pin = gueltigePin(neuePin) ? neuePin : null;
  if (!pin) return;
  aufbauen();
  $("sperre-posten").textContent = postenName;
  fehlversuche = await speicher.zustandLesen("pinFehlversuche", 0);
  gesperrtBis = await speicher.zustandLesen("pinGesperrtBis", 0);
  tastaturAufbauen();
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      verstecktSeit = Date.now();
    } else if (verstecktSeit !== null) {
      const weg = Date.now() - verstecktSeit;
      verstecktSeit = null;
      if (weg >= HINTERGRUND_FRIST_MS) sperren();
    }
  });
  sperren();
}

export function sperren() {
  if (!pin) return;
  eingabe = "";
  $("sperre-meldung").textContent = "";
  zeichnen();
  $("sperre").hidden = false;
  warten();
}

function entsperren() {
  eingabe = "";
  $("sperre").hidden = true;
}

function tastaturAufbauen() {
  const tasten = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"].map((t) => {
    if (t === "") return document.createElement("span");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "knopf sperre-taste";
    b.textContent = t;
    if (t === "⌫") {
      b.setAttribute("aria-label", "Löschen");
      b.addEventListener("click", () => {
        eingabe = eingabe.slice(0, -1);
        zeichnen();
      });
    } else {
      b.addEventListener("click", () => ziffer(t));
    }
    return b;
  });
  $("sperre-tasten").replaceChildren(...tasten);
}

function zeichnen() {
  const punkte = [];
  for (let i = 0; i < PIN_LAENGE; i++) {
    const p = document.createElement("span");
    p.className = i < eingabe.length ? "sperre-punkt voll" : "sperre-punkt";
    punkte.push(p);
  }
  $("sperre-punkte").replaceChildren(...punkte);
  $("sperre-punkte").setAttribute("aria-label", `${eingabe.length} von ${PIN_LAENGE} Ziffern eingegeben`);
}

async function ziffer(z) {
  if (Date.now() < gesperrtBis || eingabe.length >= PIN_LAENGE) return;
  eingabe += z;
  zeichnen();
  if (eingabe.length < PIN_LAENGE) return;

  if (eingabe === pin) {
    fehlversuche = 0;
    await speicher.zustandSchreiben("pinFehlversuche", 0);
    entsperren();
    return;
  }
  fehlversuche += 1;
  eingabe = "";
  zeichnen();
  if (fehlversuche >= MAX_FEHLVERSUCHE) {
    fehlversuche = 0;
    gesperrtBis = Date.now() + WARTEZEIT_MS;
    await speicher.zustandSchreiben("pinGesperrtBis", gesperrtBis);
    warten();
  } else {
    $("sperre-meldung").textContent = "Falsche PIN. Bitte erneut versuchen.";
  }
  await speicher.zustandSchreiben("pinFehlversuche", fehlversuche);
  try {
    navigator.vibrate?.([80, 60, 80]);
  } catch {
    /* Vibration ist optional */
  }
}

// Zeigt die Restwartezeit nach zu vielen Fehlversuchen und gibt die Tasten danach frei.
function warten() {
  clearTimeout(warteTimer);
  const rest = gesperrtBis - Date.now();
  const tasten = $("sperre-tasten").querySelectorAll("button");
  const gesperrt = rest > 0;
  for (const t of tasten) t.disabled = gesperrt;
  if (!gesperrt) {
    if ($("sperre-meldung").dataset.warten) {
      $("sperre-meldung").textContent = "";
      delete $("sperre-meldung").dataset.warten;
    }
    return;
  }
  $("sperre-meldung").dataset.warten = "1";
  $("sperre-meldung").textContent =
    `Zu viele Fehlversuche. Bitte ${Math.ceil(rest / 1000)} Sekunden warten.`;
  warteTimer = setTimeout(warten, Math.min(rest, 1000));
}
