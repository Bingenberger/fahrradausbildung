// Posten-Frontend: Einrichtung, Erfassung, Fahrsicherheit, Übertragung.
//
// Grundsatz: Eine Erfassung ohne Auffälligkeit ist ein Tap („Weiter").
// Jede Erfassung liegt in IndexedDB, bevor die Oberfläche reagiert.
// /p/demo ist ein Übungsmodus mit Beispieldaten ohne Server.

import { BEISPIEL_KONFIG } from "./beispiel.js";
import {
  STUFEN,
  durchgangsEreignis,
  gueltigeDurchgaenge,
  naechsteDurchgangNr,
  naechsteNummer,
  sicherheitJeNummer,
  sicherheitsEreignis,
  stornoEreignis,
} from "./logik.js";
import { offlineEinrichten } from "./offline.js";
import * as speicher from "./speicher.js";
import * as verbindung from "./verbindung.js";
import * as wach from "./wachbleiben.js";

const RUECKGAENGIG_MS = 10_000;
// Schutz gegen Doppeltipp auf „Weiter": Kinder kommen alle 20–30 s, nie in 0,7 s.
const DOPPELTIPP_SPERRE_MS = 700;
const WIEDERHOLEN_MS = 60_000;

const $ = (id) => document.getElementById(id);

const zustand = {
  konfig: null,
  ereignisse: [],
  aktuell: null,
  markiert: new Set(),
  letzte: null, // { ereignis, nummer, markiert } für Rückgängig
  rueckgaengigTimer: null,
  sperreBis: 0,
  bewertungNummer: null,
  token: null,
  demo: false,
  offlineBereit: false,
  uebertraegt: false,
  zugangUngueltig: false,
};

// ------------------------------------------------------------------ Hilfen

function element(tag, klasse, text) {
  const el = document.createElement(tag);
  if (klasse) el.className = klasse;
  if (text !== undefined) el.textContent = text;
  return el;
}

function zeige(id) {
  for (const v of ["laden", "fehler", "fertig", "einrichtung", "haupt"]) $(v).hidden = v !== id;
}

function istInstalliert() {
  return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
}

function blitz(text, art = "") {
  const b = $("blitz");
  $("blitz-text").textContent = text;
  b.className = "blitz";
  void b.offsetWidth; // Animation neu starten
  b.className = `blitz an ${art}`.trim();
  try {
    navigator.vibrate?.(art === "fehler" ? [80, 60, 80] : 40);
  } catch {
    /* Vibration ist optional */
  }
}

function tokenAusPfad() {
  const teile = location.pathname.split("/").filter(Boolean);
  return teile[0] === "p" ? teile[1] : null;
}

// ------------------------------------------------------------------ Start

function fehlerZeigen(text) {
  $("fehler-text").textContent = text;
  zeige("fehler");
}

async function start() {
  speicher.dauerhaftAnfordern();
  document.addEventListener("contextmenu", (e) => e.preventDefault());
  document.addEventListener("gesturestart", (e) => e.preventDefault());

  const token = tokenAusPfad();
  const parameter = new URLSearchParams(location.search);
  if (!token) return fehlerZeigen("Ungültige Adresse.");
  zustand.token = token;
  zustand.demo = token === "demo";
  if (zustand.demo && parameter.has("zuruecksetzen")) await speicher.allesLoeschen();

  const konfig = await konfigBestimmen(token);
  if (!konfig) return;
  zustand.konfig = konfig;
  zustand.konfig.items.sort((a, b) => a.position - b.position);
  zustand.ereignisse = await speicher.alleEreignisse();
  zustand.aktuell = await speicher.zustandLesen("aktuelleNummer", konfig.startnummern[0]);
  if (!konfig.startnummern.includes(zustand.aktuell)) zustand.aktuell = konfig.startnummern[0];

  verdrahten();

  const gestartet = await speicher.zustandLesen("gestartet", false);
  if (!gestartet || parameter.has("einrichtung")) einrichtungZeigen();
  else hauptZeigen();

  offlineVorbereiten();
  if (!zustand.demo) {
    window.addEventListener("online", () => uebertragen());
    // Fehlgeschlagene Übertragungen regelmäßig erneut versuchen – nur wenn etwas offen ist.
    setInterval(async () => {
      if ((await speicher.anzahlNichtUebertragen()) > 0) uebertragen();
    }, WIEDERHOLEN_MS);
    if ((await speicher.anzahlNichtUebertragen()) > 0) uebertragen();
  }
}

// Konfiguration bestimmen: vom Server (online) oder aus IndexedDB (offline).
// Zeigt bei Problemen selbst eine Meldung und liefert dann null.
async function konfigBestimmen(token) {
  let gespeichert = await speicher.konfigLesen();
  const wechsel = gespeichert && gespeichert.token !== token;

  // Gerät war bisher für einen anderen Posten oder Lauf eingerichtet:
  // Offene Erfassungen zuerst übertragen – sonst kein Wechsel.
  if (wechsel && gespeichert.token !== "demo" && (await speicher.anzahlNichtUebertragen()) > 0) {
    await verbindung.hochladen(gespeichert.token);
    const offen = await speicher.anzahlNichtUebertragen();
    if (offen > 0) {
      fehlerZeigen(
        `Auf diesem iPad liegen noch ${offen} nicht übertragene Erfassungen von „${gespeichert.posten.name}“. ` +
          "Bitte das iPad ins WLAN bringen und es erneut versuchen – sonst gehen diese Daten verloren.",
      );
      return null;
    }
  }

  if (zustand.demo) {
    if (gespeichert && !wechsel) return gespeichert;
    await speicher.allesLoeschen();
    const konfig = { ...BEISPIEL_KONFIG, token };
    await speicher.konfigSchreiben(konfig);
    return konfig;
  }

  const erg = await verbindung.konfigHolen(token);
  if (erg.status === "ok") {
    // Alte Daten erst ersetzen, wenn die neue Konfiguration sicher da ist.
    if (wechsel) await speicher.allesLoeschen();
    const konfig = { ...erg.daten, token };
    await speicher.konfigSchreiben(konfig);
    return konfig;
  }
  if (erg.status === "ungueltig") {
    if (gespeichert && !wechsel) {
      // Lauf abgeschlossen oder Zugang entwertet. Offene Daten nie verwerfen.
      if ((await speicher.anzahlNichtUebertragen()) === 0) {
        await abschliessen(gespeichert);
        return null;
      }
      zustand.zugangUngueltig = true;
      return gespeichert;
    }
    fehlerZeigen(
      "Dieser Zugang ist ungültig oder abgelaufen. Bitte den QR-Code auf dem Posten-Blatt erneut scannen " +
        "oder die Lehrkraft fragen.",
    );
    return null;
  }
  // Keine Verbindung
  if (gespeichert && !wechsel) return gespeichert;
  fehlerZeigen(
    wechsel
      ? `Dieses iPad ist für „${gespeichert.posten.name}“ eingerichtet. Zum Wechseln des Postens muss es im WLAN sein.`
      : "Keine Verbindung. Zum Einrichten muss das iPad im WLAN sein.",
  );
  return null;
}

async function offlineVorbereiten() {
  const anzeige = $("einrichtung-offline");
  anzeige.className = "status-offline";
  anzeige.textContent = "Wird für den Offline-Betrieb vorbereitet …";
  const erg = await offlineEinrichten();
  zustand.offlineBereit = erg.bereit;
  anzeige.textContent = erg.bereit ? "✓ offline einsatzbereit" : `⚠ Noch nicht offline einsatzbereit. ${erg.grund}`;
  anzeige.className = `status-offline ${erg.bereit ? "bereit" : "warnung"}`;
}

// ------------------------------------------------------------------ Lauf wechseln

function datumKurz(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", {
    weekday: "short",
    day: "numeric",
    month: "long",
  });
}

// Bietet die anderen Läufe dieses Postens an. Beide Adressen liegen im
// Geltungsbereich /p/, deshalb bleibt der Wechsel in der installierten App –
// es entsteht kein zweites Symbol auf dem Home-Bildschirm.
function wechselAnbieten(bereichId, weitere) {
  const bereich = $(bereichId);
  bereich.hidden = !weitere || weitere.length === 0;
  if (bereich.hidden) return;
  const hinweis = $(bereichId + "-hinweis");
  hinweis.hidden = true;
  $(bereichId + "-liste").replaceChildren(
    ...weitere.map((l) => {
      const knopf = element("button", "knopf knopf-neben", `${l.gruppe} · ${datumKurz(l.datum)}`);
      knopf.type = "button";
      knopf.addEventListener("click", () => {
        // Ohne Netz ließe sich die neue Klasse nicht laden – dann lieber nichts tun,
        // als die eingerichtete App gegen eine leere einzutauschen.
        if (!navigator.onLine) {
          hinweis.hidden = false;
          return;
        }
        location.replace("/p/" + l.token);
      });
      return knopf;
    }),
  );
}

// Alle Daten sind beim Server und der Lauf ist abgeschlossen: lokale Kopie löschen.
// Nie vorher – solange der Lauf läuft, sind die lokalen Daten die einzige Kopie.
// ``konfig`` nur, wenn zustand.konfig noch nicht steht (Zugang beim Start ungültig).
async function abschliessen(konfig) {
  const weitere = ((konfig || zustand.konfig) || {}).weitere_laeufe;
  await speicher.allesLoeschen();
  await wach.loslassen();
  wechselAnbieten("fertig-wechsel", weitere);
  zeige("fertig");
}

// ------------------------------------------------------------------ Übertragung

async function uebertragen({ manuell = false } = {}) {
  if (zustand.demo || zustand.uebertraegt) return;
  zustand.uebertraegt = true;
  const knopf = $("uebertragen");
  knopf.disabled = true;
  knopf.textContent = "überträgt …";
  try {
    const erg = await verbindung.hochladen(zustand.token);
    zustand.ereignisse = await speicher.alleEreignisse();
    if (erg.status === "ungueltig") {
      zustand.zugangUngueltig = true;
      if (manuell) blitz("Zugang ungültig – Lehrkraft fragen", "fehler");
    } else if (erg.status === "fehler") {
      if (manuell) blitz("Keine Verbindung – später nochmal", "fehler");
    } else {
      zustand.zugangUngueltig = false;
      if (manuell) blitz("✓ übertragen");
      // Alles beim Server? Dann prüfen, ob der Lauf inzwischen abgeschlossen ist.
      if ((await speicher.anzahlNichtUebertragen()) === 0) {
        const status = await verbindung.serverStatus(zustand.token);
        if (status.status === "ungueltig") return abschliessen();
      }
    }
  } finally {
    zustand.uebertraegt = false;
    knopf.disabled = false;
    knopf.textContent = "Jetzt übertragen";
    statusZeichnen();
  }
}

// ------------------------------------------------------------------ Einrichtung

function einrichtungZeigen() {
  const k = zustand.konfig;
  $("einrichtung-posten").textContent = k.posten.name;
  $("einrichtung-status").textContent = zustand.demo
    ? `${k.startnummern.length} Startnummern · Übungsmodus`
    : `${k.startnummern.length} Startnummern geladen`;
  $("anleitung-installieren").hidden = istInstalliert();
  $("einrichtung-wach").textContent = wach.unterstuetzt()
    ? "Das Display bleibt während der Prüfung an."
    : "Dieses iPad kann das Display nicht von selbst anlassen. Bitte unter "
      + "Einstellungen → Anzeige & Helligkeit → Automatische Sperre „Nie“ wählen.";
  $("einrichtung-wach").className = wach.unterstuetzt() ? "status-ok" : "status-offline warnung";
  $("prototyp-hinweis").hidden = !zustand.demo;
  const liste = $("einrichtung-items");
  liste.replaceChildren(...k.items.map((i) => element("li", "", i.kurzbezeichnung)));
  wechselAnbieten("einrichtung-wechsel", k.weitere_laeufe);
  zeige("einrichtung");
}

// ------------------------------------------------------------------ Hauptansicht

function hauptZeigen() {
  $("status-posten").textContent = zustand.konfig.posten.name;
  $("uebertragen").hidden = zustand.demo;
  itemsAufbauen();
  reiterWaehlen("erfassung");
  erfassungZeichnen();
  statusZeichnen();
  zeige("haupt");
  // Nicht abwarten: die Erfassung darf darauf nicht warten müssen.
  wach.halten().then(statusZeichnen);
}

async function statusZeichnen() {
  const n = await speicher.anzahlNichtUebertragen();
  const abgewiesen = await speicher.anzahlAbgewiesen();
  let text =
    n === 0 ? "0 · alles übertragen" : `${n} ${n === 1 ? "Erfassung" : "Erfassungen"} · nicht übertragen`;
  if (zustand.demo) text = `${zustand.ereignisse.length} Erfassungen · Übungsmodus`;
  if (abgewiesen) text += ` · ${abgewiesen} abgewiesen`;
  if (zustand.zugangUngueltig && n > 0) text += " · Zugang ungültig, Lehrkraft fragen";
  // Energiesparmodus o. Ä.: Die Aufsicht soll nicht glauben, das Display bleibe an.
  const displaySperrt = wach.unterstuetzt() && wach.versucht() && !wach.aktiv();
  if (displaySperrt) text += " · Display sperrt sich";
  const zaehler = $("status-zaehler");
  zaehler.textContent = text;
  zaehler.classList.toggle(
    "warnung",
    Boolean(abgewiesen || (zustand.zugangUngueltig && n > 0) || displaySperrt),
  );
  const online = navigator.onLine;
  const netz = $("status-netz");
  netz.textContent = online ? "online" : "offline";
  netz.classList.toggle("offline", !online);
}

function itemsAufbauen() {
  const knoepfe = zustand.konfig.items.map((item) => {
    const b = element("button", "item");
    b.type = "button";
    b.dataset.itemId = String(item.id);
    b.setAttribute("aria-pressed", "false");
    b.append(element("span", "item-name", item.kurzbezeichnung), element("span", "item-zustand", ""));
    b.addEventListener("click", () => itemUmschalten(item.id));
    return b;
  });
  $("items").replaceChildren(...knoepfe);
}

function itemUmschalten(id) {
  if (zustand.markiert.has(id)) zustand.markiert.delete(id);
  else zustand.markiert.add(id);
  itemsZeichnen();
}

function itemsZeichnen() {
  for (const b of $("items").children) {
    const an = zustand.markiert.has(Number(b.dataset.itemId));
    b.setAttribute("aria-pressed", String(an));
    b.querySelector(".item-zustand").textContent = an ? "✗ vergessen" : "";
  }
}

function erfassungZeichnen() {
  const nr = zustand.aktuell;
  $("nummer").textContent = String(nr);
  $("durchgang").textContent = `Durchgang ${naechsteDurchgangNr(zustand.ereignisse, nr)}`;
  itemsZeichnen();
}

async function nummerSetzen(nr) {
  zustand.aktuell = nr;
  await speicher.zustandSchreiben("aktuelleNummer", nr);
  erfassungZeichnen();
}

async function weiter() {
  const jetzt = Date.now();
  if (jetzt < zustand.sperreBis) return;
  zustand.sperreBis = jetzt + DOPPELTIPP_SPERRE_MS;

  const nr = zustand.aktuell;
  const fehlend = zustand.konfig.items.filter((i) => zustand.markiert.has(i.id)).map((i) => i.id);
  const ereignis = durchgangsEreignis(nr, naechsteDurchgangNr(zustand.ereignisse, nr), fehlend);

  try {
    await speicher.ereignisSpeichern(ereignis);
  } catch (err) {
    console.error("Speichern fehlgeschlagen", err);
    blitz("Nicht gespeichert – bitte nochmal tippen", "fehler");
    zustand.sperreBis = 0;
    return;
  }
  zustand.ereignisse.push(ereignis);

  zustand.letzte = { ereignis, nummer: nr, markiert: [...zustand.markiert] };
  zustand.markiert.clear();
  await nummerSetzen(naechsteNummer(zustand.konfig.startnummern, nr));

  blitz(`✓ Nr. ${nr}`);
  const zusatz = fehlend.length ? ` · ${fehlend.length} vergessen` : " · alles richtig";
  rueckgaengigAnbieten(`Nr. ${nr} gespeichert${zusatz}`);
  statusZeichnen();
}

function rueckgaengigAnbieten(text) {
  clearTimeout(zustand.rueckgaengigTimer);
  $("rueckgaengig-text").textContent = text;
  $("rueckgaengig-inhalt").hidden = false;
  const balken = $("rueckgaengig-balken");
  balken.style.setProperty("--dauer", `${RUECKGAENGIG_MS}ms`);
  balken.classList.remove("laeuft");
  void balken.offsetWidth;
  balken.classList.add("laeuft");
  zustand.rueckgaengigTimer = setTimeout(rueckgaengigBeenden, RUECKGAENGIG_MS);
}

function rueckgaengigBeenden() {
  clearTimeout(zustand.rueckgaengigTimer);
  zustand.letzte = null;
  $("rueckgaengig-inhalt").hidden = true;
}

async function rueckgaengig() {
  const letzte = zustand.letzte;
  if (!letzte) return;
  // Nicht löschen: ein neues Ereignis storniert die letzte Erfassung.
  const storno = stornoEreignis(letzte.nummer, letzte.ereignis.nutzlast.durchgang_nr);
  try {
    await speicher.ereignisSpeichern(storno);
  } catch (err) {
    console.error("Speichern fehlgeschlagen", err);
    blitz("Nicht gespeichert – bitte nochmal tippen", "fehler");
    return;
  }
  zustand.ereignisse.push(storno);
  rueckgaengigBeenden();
  zustand.markiert = new Set(letzte.markiert);
  await nummerSetzen(letzte.nummer);
  blitz(`Nr. ${letzte.nummer} zurück`, "storno");
  statusZeichnen();
}

async function ueberspringen() {
  zustand.markiert.clear();
  await nummerSetzen(naechsteNummer(zustand.konfig.startnummern, zustand.aktuell));
}

// ------------------------------------------------------------------ Nummernwahl

function nummernwahlOeffnen() {
  const durchgaenge = gueltigeDurchgaenge(zustand.ereignisse);
  const zellen = zustand.konfig.startnummern.map((nr) => {
    const z = element("button", "zelle");
    z.type = "button";
    if (nr === zustand.aktuell) z.classList.add("aktuell");
    const anzahl = durchgaenge.get(nr)?.length ?? 0;
    z.append(element("span", "zelle-nummer", String(nr)), element("span", "zelle-info", `${anzahl}× erfasst`));
    z.setAttribute("aria-label", `Nummer ${nr}, ${anzahl} mal erfasst`);
    z.addEventListener("click", async () => {
      // Markierte Items bleiben stehen: sie gehören zum beobachteten Kind,
      // nur die Nummer war falsch.
      $("nummernwahl").hidden = true;
      await nummerSetzen(nr);
    });
    return z;
  });
  $("nummernwahl-raster").replaceChildren(...zellen);
  $("nummernwahl").hidden = false;
}

// ------------------------------------------------------------------ Fahrsicherheit

function reiterWaehlen(name) {
  const erfassung = name === "erfassung";
  $("reiter-erfassung").setAttribute("aria-selected", String(erfassung));
  $("reiter-sicherheit").setAttribute("aria-selected", String(!erfassung));
  $("ansicht-erfassung").hidden = !erfassung;
  $("ansicht-sicherheit").hidden = erfassung;
  if (!erfassung) sicherheitsrasterZeichnen();
}

function sicherheitsrasterZeichnen() {
  const bewertungen = sicherheitJeNummer(zustand.ereignisse);
  const zellen = zustand.konfig.startnummern.map((nr) => {
    const z = element("button", "zelle");
    z.type = "button";
    const e = bewertungen.get(nr);
    const stufe = e && STUFEN.find((s) => s.stufe === e.nutzlast.stufe);
    if (stufe) z.classList.add(`stufe-${stufe.stufe}`);
    z.append(
      element("span", "zelle-nummer", String(nr)),
      element("span", "zelle-info", stufe ? `${stufe.symbol} ${stufe.text}` : "offen"),
    );
    z.addEventListener("click", () => bewertungOeffnen(nr));
    return z;
  });
  $("sicherheit-raster").replaceChildren(...zellen);
}

function aktuelleBewertung(nr) {
  return sicherheitJeNummer(zustand.ereignisse).get(nr)?.nutzlast ?? null;
}

function bewertungOeffnen(nr) {
  zustand.bewertungNummer = nr;
  const bisher = aktuelleBewertung(nr);
  $("bewertung-titel").textContent = `Nr. ${nr} – Fahrsicherheit`;
  $("bewertung-bemerkung").value = bisher?.bemerkung ?? "";
  $("bewertung-meldung").textContent = "";
  const knoepfe = STUFEN.map((s) => {
    const b = element("button", `knopf stufe stufe-${s.stufe}`, `${s.symbol}  ${s.text}`);
    b.type = "button";
    b.dataset.stufe = String(s.stufe);
    b.addEventListener("click", () => bewertungSpeichern(s.stufe));
    return b;
  });
  $("bewertung-stufen").replaceChildren(...knoepfe);
  stufenZeichnen();
  $("bewertung").hidden = false;
}

function stufenZeichnen() {
  const bisher = aktuelleBewertung(zustand.bewertungNummer);
  for (const b of $("bewertung-stufen").children) {
    b.setAttribute("aria-pressed", String(bisher?.stufe === Number(b.dataset.stufe)));
  }
}

async function bewertungSpeichern(stufe) {
  const nr = zustand.bewertungNummer;
  const bemerkung = $("bewertung-bemerkung").value.trim();
  const ereignis = sicherheitsEreignis(nr, stufe, bemerkung);
  try {
    await speicher.ereignisSpeichern(ereignis);
  } catch (err) {
    console.error("Speichern fehlgeschlagen", err);
    blitz("Nicht gespeichert – bitte nochmal tippen", "fehler");
    return false;
  }
  zustand.ereignisse.push(ereignis);
  $("bewertung-meldung").textContent = "";
  stufenZeichnen();
  blitz(`✓ Nr. ${nr}`);
  statusZeichnen();
  return true;
}

async function bewertungSchliessen() {
  const bisher = aktuelleBewertung(zustand.bewertungNummer);
  const bemerkung = $("bewertung-bemerkung").value.trim();
  if (bemerkung !== (bisher?.bemerkung ?? "")) {
    if (!bisher) {
      $("bewertung-meldung").textContent = "Bitte zuerst sicher, teilweise sicher oder unsicher wählen.";
      return;
    }
    if (!(await bewertungSpeichern(bisher.stufe))) return;
  }
  $("bewertung-bemerkung").blur();
  $("bewertung").hidden = true;
  sicherheitsrasterZeichnen();
}

// ------------------------------------------------------------------ Ereignisse verdrahten

function verdrahten() {
  $("start").addEventListener("click", async () => {
    await speicher.zustandSchreiben("gestartet", true);
    history.replaceState(null, "", location.pathname);
    hauptZeigen();
  });
  $("zuruecksetzen").addEventListener("click", async () => {
    await speicher.allesLoeschen();
    location.replace(location.pathname);
  });

  // pointerdown statt click wäre schneller, löst aber beim Scrollen aus.
  $("weiter").addEventListener("click", weiter);
  $("rueckgaengig-knopf").addEventListener("click", rueckgaengig);
  $("ueberspringen").addEventListener("click", ueberspringen);
  $("andere-nummer").addEventListener("click", nummernwahlOeffnen);
  $("nummernwahl-abbrechen").addEventListener("click", () => ($("nummernwahl").hidden = true));

  $("reiter-erfassung").addEventListener("click", () => reiterWaehlen("erfassung"));
  $("reiter-sicherheit").addEventListener("click", () => reiterWaehlen("sicherheit"));
  $("bewertung-fertig").addEventListener("click", bewertungSchliessen);

  $("uebertragen").addEventListener("click", () => uebertragen({ manuell: true }));
  window.addEventListener("online", statusZeichnen);
  window.addEventListener("offline", statusZeichnen);
}

$("erneut").addEventListener("click", () => location.reload());

start().catch((err) => {
  console.error(err);
  $("fehler-text").textContent = "Die App konnte nicht starten. Bitte neu öffnen.";
  zeige("fehler");
});
