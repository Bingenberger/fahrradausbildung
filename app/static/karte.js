// Streckenplanung auf der Karte (Verwaltungsbereich).
//
// Grundlage ist der eigenständige Kartengenerator fahrradpruefung-karten.html.
// Unterschiede: eine Linie je Strecke, Posten statt „Stationen", gespeichert wird
// auf dem Server (Formular mit CSRF-Feld) statt im Browser.
//
// Wegen der Content-Security-Policy: keine Inline-Styles in HTML-Schnipseln –
// Markierungen bekommen nur Klassen (app/static/karte.css).

(function () {
  "use strict";

  const daten = JSON.parse(document.getElementById("kartendaten").textContent);
  const Q = daten.quellen;
  const $ = (id) => document.getElementById(id);

  const LINIENFARBE = "#c62828";
  const DEUTSCHLAND = [[51.1657, 10.4515], 6];

  // ------------------------------------------------------------------ Zustand

  const v = daten.strecke.verlauf || {};
  const zustand = {
    modus: "posten",
    streckenmodus: v.modus || "route", // route | trace | import
    wegpunkte: (v.wegpunkte || []).slice(),
    spur: v.modus === "trace" || v.modus === "import" ? (v.linie || []).slice() : [],
    linie: (v.linie || []).slice(),
    posten: daten.posten.map((p) => ({ ...p })),
    gewaehlt: null,
    geaendert: false,
  };
  const erster = zustand.posten.find((p) => !p.ort) || zustand.posten[0];
  zustand.gewaehlt = erster ? erster.id : null;

  function geaendert() {
    zustand.geaendert = true;
    $("ungespeichert").hidden = false;
  }

  // ------------------------------------------------------------------ Karte

  // maxZoom gilt für alle Kartenstile; die Kachelebene bekommt zusätzlich maxNativeZoom.
  // Sonst sinkt beim Wechsel auf einen gröberen Stil die Obergrenze der Karte unter die
  // aktuelle Zoomstufe – Leaflet lädt dann gar keine Kacheln mehr und zeigt nur Grau.
  const karte = L.map("karte", { zoomControl: true, maxZoom: Q.maxZoom });
  L.control.scale({ imperial: false, metric: true }).addTo(karte);

  let quelle = "cyclosm";
  try {
    const gemerkt = localStorage.getItem("fp-kartenquelle");
    if (gemerkt && Q.kacheln[gemerkt]) quelle = gemerkt;
  } catch (e) {}

  let kachelEbene = null;

  // Die Zoomgrenze aus app/kartenquellen.py ist das Versprechen des Dienstes.
  // Ob er eine Stufe auch für diesen Ort gerendert hat, zeigt erst der Abruf:
  // CyclOSM liefert über Niederkassel ab Stufe 18 nichts mehr, über Nürnberg
  // schon. Kommt aus einer Stufe gar keine Kachel, merken wir uns für diese
  // Quelle die Stufe darunter; Leaflet vergrößert dann deren Bilder, statt die
  // Karte grau zu lassen. Nur für diesen Seitenaufruf – die Lücken wandern.
  const gelernt = {};
  const FEHLER_BIS_RUECKZUG = 3;
  const RUECKZUG_FRIST = 1200; // ms abwarten: vielleicht kommen doch noch Kacheln
  const KLEINSTE_GRENZE = 12;

  function grenze() {
    const g = gelernt[quelle];
    return g === undefined ? Q.kacheln[quelle].maxNativeZoom : g;
  }

  function kachelstufe() {
    return Math.min(Math.round(karte.getZoom()), grenze());
  }

  function quelleAnwenden() {
    const schluessel = quelle;
    const s = Q.kacheln[schluessel];
    if (kachelEbene) karte.removeLayer(kachelEbene);
    const fehler = {}, geladen = {};
    let geplant = false;
    kachelEbene = L.tileLayer(s.url, {
      subdomains: s.subs.length ? s.subs : "abc",
      maxZoom: Q.maxZoom,
      maxNativeZoom: grenze(),
      crossOrigin: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende',
    });
    kachelEbene.on("tileload", (e) => { geladen[e.coords.z] = true; });
    kachelEbene.on("tileerror", (e) => {
      const z = e.coords ? e.coords.z : -1;
      if (geplant || z !== kachelstufe()) return;
      fehler[z] = (fehler[z] || 0) + 1;
      if (fehler[z] < FEHLER_BIS_RUECKZUG) return;
      geplant = true;
      setTimeout(() => { geplant = false; zurueckziehen(schluessel, z, geladen); }, RUECKZUG_FRIST);
    });
    kachelEbene.addTo(karte);
    $("quelle-nennung").textContent = s.attr;
    zoomHinweis();
  }

  function zurueckziehen(schluessel, z, geladen) {
    if (schluessel !== quelle || z > grenze()) return; // Kartenstil inzwischen gewechselt
    if (geladen[z]) return; // es fehlten nur einzelne Kacheln
    if (z - 1 < KLEINSTE_GRENZE) {
      status("Dieser Kartenserver liefert gerade keine Bilder. Bitte einen anderen Kartenstil wählen.", 10000);
      return;
    }
    gelernt[schluessel] = z - 1;
    status(Q.kacheln[schluessel].label + " hat hier ab Zoomstufe " + z + " keine eigenen Bilder. "
      + "Die Karte wird vergrößert dargestellt – mit einem anderen Kartenstil wird sie schärfer.", 12000);
    quelleAnwenden();
  }

  // Oberhalb der Kachelgrenze vergrößert Leaflet die letzten Bilder: sichtbar, aber unscharf.
  function zoomHinweis() {
    const g = grenze();
    const el = $("zoom-hinweis");
    el.hidden = !(karte.getZoom() > g);
    el.textContent = "Ab Zoomstufe " + (g + 1) + " hat dieser Kartenstil hier keine eigenen Bilder mehr: "
      + "Die Karte wird vergrößert und dadurch unscharf. Ein anderer Kartenstil kann hier schärfer sein.";
  }
  karte.on("zoomend", zoomHinweis);

  const auswahl = $("quelle");
  for (const [schluessel, s] of Object.entries(Q.kacheln)) {
    const o = document.createElement("option");
    o.value = schluessel;
    o.textContent = s.label;
    auswahl.appendChild(o);
  }
  auswahl.value = quelle;
  auswahl.addEventListener("change", () => {
    quelle = auswahl.value;
    try { localStorage.setItem("fp-kartenquelle", quelle); } catch (e) {}
    quelleAnwenden();
  });

  function status(text, ms) {
    const el = $("karte-status");
    if (!text) { el.hidden = true; return; }
    el.textContent = text;
    el.hidden = false;
    if (ms) setTimeout(() => { if (el.textContent === text) el.hidden = true; }, ms);
  }

  // ------------------------------------------------------------------ Geometrie

  function abstand(a, b) {
    const R = 6371000, r = Math.PI / 180;
    const dLat = (b[0] - a[0]) * r, dLon = (b[1] - a[1]) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  function laenge(pts) {
    let m = 0;
    for (let i = 1; i < pts.length; i++) m += abstand(pts[i - 1], pts[i]);
    return m;
  }
  function laengeText(m) {
    if (!m) return "–";
    return m < 1000 ? Math.round(m) + " m" : (m / 1000).toFixed(2).replace(".", ",") + " km";
  }
  function polylinie(str, stellen) {
    let i = 0, lat = 0, lng = 0;
    const out = [], f = Math.pow(10, stellen || 5);
    while (i < str.length) {
      for (const achse of [0, 1]) {
        let b, shift = 0, wert = 0;
        do { b = str.charCodeAt(i++) - 63; wert |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
        const d = wert & 1 ? ~(wert >> 1) : wert >> 1;
        if (achse === 0) lat += d; else lng += d;
      }
      out.push([lat / f, lng / f]);
    }
    return out;
  }

  // ------------------------------------------------------------------ Routing
  // Welche Wege befahrbar sind, entscheidet das Profil des Dienstes. Fällt der
  // gewählte Dienst aus, versucht die Seite die anderen der Reihe nach.

  const DIENSTE = {
    "osrm-bike": { art: "osrm", url: Q.routing.osrm_bike, label: "Fahrrad – Radwege einbezogen",
      hinweis: "Nutzt Straßen, Radwege und für Radfahrer freigegebene Wege. In der Regel die richtige Wahl." },
    "osrm-foot": { art: "osrm", url: Q.routing.osrm_foot, label: "Fuß- und Radwege",
      hinweis: "Bezieht reine Fußwege ein. Bitte vor Ort prüfen, ob die Kinder dort fahren dürfen." },
    "valhalla-bike": { art: "valhalla", costing: "bicycle", label: "Fahrrad – zweiter Dienst",
      optionen: { bicycle: { bicycle_type: "Hybrid", use_roads: 0.25, avoid_bad_surfaces: 0.25 } },
      hinweis: "Zweiter Anbieter mit Fahrradprofil – hilfreich, wenn der erste keine Strecke findet." },
    "valhalla-ped": { art: "valhalla", costing: "pedestrian", label: "Fuß- und Radwege – zweiter Dienst",
      optionen: { pedestrian: { walking_speed: 5.0, step_penalty: 900, use_ferry: 0 } },
      hinweis: "Zweiter Anbieter mit Fußprofil; Treppen werden gemieden." },
    "osrm-car": { art: "osrm", url: Q.routing.osrm_car, label: "Nur Straßen",
      hinweis: "Bleibt auf Straßen; Fuß- und Radwege werden nicht genutzt." },
    line: { art: "linie", label: "Luftlinie", hinweis: "Verbindet die Wegpunkte gerade." },
  };
  const RUECKFALL = ["osrm-bike", "valhalla-bike", "osrm-foot", "valhalla-ped", "osrm-car"];

  const routingWahl = $("routing");
  try {
    const gemerkt = localStorage.getItem("fp-routing");
    if (gemerkt && DIENSTE[gemerkt]) routingWahl.value = gemerkt;
  } catch (e) {}
  function routingHinweis() { $("routing-hinweis").textContent = DIENSTE[routingWahl.value].hinweis; }

  async function osrm(d, wp) {
    const koord = wp.map((p) => p[1].toFixed(6) + "," + p[0].toFixed(6)).join(";");
    const frage = async (ohneWenden) => {
      const r = await fetch(d.url + koord + "?overview=full&geometries=geojson&continue_straight=" + ohneWenden);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      if (!j.routes || !j.routes.length) throw new Error("keine Route");
      return j.routes[0].geometry.coordinates.map((c) => [c[1], c[0]]);
    };
    if (!$("kein-wenden").checked) return frage(false);
    try { return await frage(true); } catch (e) { return frage(false); } // Sackgasse: dann eben wenden
  }

  async function valhalla(d, wp) {
    const ohneWenden = $("kein-wenden").checked;
    const r = await fetch(Q.routing.valhalla, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        locations: wp.map((p, i) => ({
          lat: p[0], lon: p[1],
          type: ohneWenden && i > 0 && i < wp.length - 1 ? "break_through" : "break",
        })),
        costing: d.costing,
        costing_options: d.optionen,
        directions_options: { units: "kilometers", language: "de-DE" },
      }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    if (!j.trip || !j.trip.legs) throw new Error("keine Route");
    const out = [];
    for (const leg of j.trip.legs) out.push(...polylinie(leg.shape, 6));
    if (!out.length) throw new Error("leere Route");
    return out;
  }

  function mitDienst(schluessel, wp) {
    const d = DIENSTE[schluessel];
    if (d.art === "linie") return Promise.resolve(wp.slice());
    return d.art === "valhalla" ? valhalla(d, wp) : osrm(d, wp);
  }

  let routingLauf = 0;
  async function linieBerechnen() {
    if (zustand.streckenmodus !== "route") { zustand.linie = zustand.spur.slice(); zeichnen(); return; }
    const wp = zustand.wegpunkte;
    if (wp.length < 2 || routingWahl.value === "line") { zustand.linie = wp.slice(); zeichnen(); return; }

    const lauf = ++routingLauf;
    status("Strecke wird berechnet …");
    const gewaehlt = routingWahl.value;
    const reihenfolge = [gewaehlt, ...RUECKFALL.filter((k) => k !== gewaehlt)];
    for (const schluessel of reihenfolge) {
      try {
        const geo = await mitDienst(schluessel, wp);
        if (lauf !== routingLauf) return;
        zustand.linie = geo;
        zeichnen();
        if (schluessel === gewaehlt) status(null);
        else status("„" + DIENSTE[gewaehlt].label + "“ antwortet nicht. Berechnet mit „" + DIENSTE[schluessel].label + "“.", 9000);
        return;
      } catch (e) { /* nächster Dienst */ }
    }
    if (lauf !== routingLauf) return;
    zustand.linie = wp.slice();
    zeichnen();
    status("Kein Routing-Dienst erreichbar – die Punkte werden gerade verbunden. Mit „frei zeichnen“ geht es von Hand.", 10000);
  }

  // ------------------------------------------------------------------ Zeichnen

  const ebenen = [];
  const andereEbenen = {};
  function weg(liste) { liste.forEach((l) => karte.removeLayer(l)); liste.length = 0; }

  function postenSymbol(p) {
    const el = document.createElement("div");
    el.className = "posten-marke" + (p.id === zustand.gewaehlt ? " gewaehlt" : "");
    el.textContent = String(p.nummer);
    return L.divIcon({ className: "", html: el, iconSize: [28, 28], iconAnchor: [14, 14] });
  }

  function zeichnen() {
    weg(ebenen);
    if (zustand.linie.length >= 2) {
      ebenen.push(L.polyline(zustand.linie, { color: "#ffffff", weight: 11, opacity: 0.9, lineJoin: "round", lineCap: "round" }).addTo(karte));
      ebenen.push(L.polyline(zustand.linie, { color: LINIENFARBE, weight: 6, opacity: 1, lineJoin: "round", lineCap: "round" }).addTo(karte));
    }
    if (zustand.streckenmodus === "route" && zustand.modus === "route") {
      zustand.wegpunkte.forEach((p, k) => {
        const el = document.createElement("div");
        el.className = "wegpunkt";
        const m = L.marker(p, { draggable: true, icon: L.divIcon({ className: "", html: el, iconSize: [12, 12], iconAnchor: [6, 6] }) }).addTo(karte);
        m.on("dragend", (e) => { const ll = e.target.getLatLng(); zustand.wegpunkte[k] = [ll.lat, ll.lng]; geaendert(); linieBerechnen(); });
        m.on("contextmenu", () => { zustand.wegpunkte.splice(k, 1); geaendert(); linieBerechnen(); });
        ebenen.push(m);
      });
    }
    for (const p of zustand.posten) {
      if (!p.ort) continue;
      const m = L.marker(p.ort, { draggable: true, icon: postenSymbol(p), title: p.nummer + ". " + p.name, zIndexOffset: 1000 }).addTo(karte);
      m.on("dragend", (e) => { const ll = e.target.getLatLng(); p.ort = [ll.lat, ll.lng]; geaendert(); postenListe(); });
      m.on("click", () => { zustand.gewaehlt = p.id; postenListe(); zeichnen(); });
      ebenen.push(m);
    }
    $("laenge").textContent = laengeText(laenge(zustand.linie));
  }

  // ------------------------------------------------------------------ Seitenleiste

  function postenListe() {
    const ol = $("posten-liste");
    ol.replaceChildren();
    for (const p of zustand.posten) {
      const li = document.createElement("li");
      const lab = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "posten-wahl";
      radio.className = "unsichtbar";
      radio.checked = p.id === zustand.gewaehlt;
      radio.addEventListener("change", () => {
        zustand.gewaehlt = p.id;
        setzeModus("posten");
        if (p.ort) karte.panTo(p.ort);
        zeichnen();
        postenListe();
      });
      const nr = document.createElement("span");
      nr.className = "posten-nr";
      nr.textContent = String(p.nummer);
      const text = document.createElement("span");
      text.textContent = p.name;
      const ort = document.createElement("span");
      ort.className = "posten-ort" + (p.ort ? "" : " fehlt");
      ort.textContent = p.ort ? "✓" : "kein Standort";
      lab.append(radio, nr, text);
      li.append(lab, ort);
      if (p.ort) {
        const loeschen = document.createElement("button");
        loeschen.type = "button";
        loeschen.className = "knopf knopf-klein";
        loeschen.textContent = "entfernen";
        loeschen.setAttribute("aria-label", "Standort von " + p.name + " entfernen");
        loeschen.addEventListener("click", () => { p.ort = null; geaendert(); postenListe(); zeichnen(); });
        li.append(loeschen);
      }
      ol.appendChild(li);
    }
  }

  function setzeModus(modus) {
    zustand.modus = modus;
    for (const r of document.getElementsByName("modus")) r.checked = r.value === modus;
    if (modus === "route" || modus === "trace") {
      if (zustand.streckenmodus === "import" && (zustand.wegpunkte.length || zustand.spur.length)) {
        status("Die Strecke stammt aus einer Datei. Zum Neuzeichnen zuerst „Strecke leeren“.", 6000);
      } else if (zustand.streckenmodus !== modus) {
        // Wechsel zwischen Wegpunkten und Freihand: von der aktuellen Linie ausgehen
        if (modus === "trace") zustand.spur = zustand.linie.slice();
        zustand.streckenmodus = modus;
      }
    }
    zeichnen();
  }
  for (const r of document.getElementsByName("modus")) r.addEventListener("change", () => setzeModus(r.value));

  function andereListe() {
    const el = $("andere-liste");
    if (!daten.andere.length) return;
    const h = document.createElement("p");
    h.className = "hilfe";
    h.textContent = "Andere Strecken zum Vergleich einblenden:";
    el.appendChild(h);
    for (const s of daten.andere) {
      const lab = document.createElement("label");
      lab.className = "andere-strecke";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.addEventListener("change", () => {
        if (cb.checked) {
          andereEbenen[s.id] = L.polyline(s.linie, { color: "#555", weight: 4, opacity: 0.6, dashArray: "6 8" }).addTo(karte);
        } else if (andereEbenen[s.id]) {
          karte.removeLayer(andereEbenen[s.id]);
          delete andereEbenen[s.id];
        }
      });
      lab.append(cb, document.createTextNode(s.name));
      el.appendChild(lab);
    }
  }

  // ------------------------------------------------------------------ Klicks

  karte.on("click", (e) => {
    const pt = [e.latlng.lat, e.latlng.lng];
    if (zustand.modus === "posten") {
      const p = zustand.posten.find((x) => x.id === zustand.gewaehlt);
      if (!p) { status("Bitte zuerst links einen Posten wählen.", 4000); return; }
      p.ort = pt;
      geaendert();
      // Gleich zum nächsten Posten ohne Standort weiterspringen
      const naechster = zustand.posten.find((x) => !x.ort);
      if (naechster) zustand.gewaehlt = naechster.id;
      postenListe();
      zeichnen();
      return;
    }
    if (zustand.streckenmodus === "import") {
      status("Die Strecke stammt aus einer Datei. Zum Neuzeichnen zuerst „Strecke leeren“.", 5000);
      return;
    }
    if (zustand.modus === "trace") zustand.spur.push(pt);
    else zustand.wegpunkte.push(pt);
    geaendert();
    linieBerechnen();
  });

  $("zurueck").addEventListener("click", () => {
    if (zustand.streckenmodus === "import") { status("Importierte Strecke – bitte „Strecke leeren“.", 4000); return; }
    if (zustand.streckenmodus === "trace") zustand.spur.pop(); else zustand.wegpunkte.pop();
    geaendert();
    linieBerechnen();
  });

  $("leeren").addEventListener("click", () => {
    zustand.wegpunkte = []; zustand.spur = []; zustand.linie = [];
    zustand.streckenmodus = zustand.modus === "trace" ? "trace" : "route";
    geaendert();
    zeichnen();
  });

  routingWahl.addEventListener("change", () => {
    routingHinweis();
    try { localStorage.setItem("fp-routing", routingWahl.value); } catch (e) {}
    linieBerechnen();
  });
  $("kein-wenden").addEventListener("change", () => linieBerechnen());

  // ------------------------------------------------------------------ Import

  function ausGeoJSON(obj) {
    const out = [];
    const lauf = (g) => {
      if (!g) return;
      if (g.type === "FeatureCollection") g.features.forEach((f) => lauf(f.geometry));
      else if (g.type === "Feature") lauf(g.geometry);
      else if (g.type === "GeometryCollection") g.geometries.forEach(lauf);
      else if (g.type === "LineString") g.coordinates.forEach((c) => out.push([c[1], c[0]]));
      else if (g.type === "MultiLineString") g.coordinates.forEach((l) => l.forEach((c) => out.push([c[1], c[0]])));
    };
    lauf(obj);
    return out;
  }

  function ausXML(text) {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("kein gültiges XML");
    const out = [];
    const trk = doc.getElementsByTagName("trkpt");
    const gpx = trk.length ? trk : doc.getElementsByTagName("rtept");
    for (const p of gpx) {
      const la = parseFloat(p.getAttribute("lat")), lo = parseFloat(p.getAttribute("lon"));
      if (isFinite(la) && isFinite(lo)) out.push([la, lo]);
    }
    if (out.length) return out;
    for (const el of doc.getElementsByTagName("*")) {
      if ((el.localName || el.nodeName) !== "coordinates") continue;
      for (const stueck of (el.textContent || "").trim().split(/\s+/)) {
        const t = stueck.split(",");
        const lo = parseFloat(t[0]), la = parseFloat(t[1]);
        if (isFinite(la) && isFinite(lo)) out.push([la, lo]);
      }
      if (out.length > 1) break;
    }
    return out;
  }

  $("datei").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const leser = new FileReader();
    leser.onload = () => {
      let pts, roh = null;
      try {
        if (/\.(geojson|json)$/i.test(f.name)) { roh = JSON.parse(String(leser.result)); pts = ausGeoJSON(roh); }
        else { pts = ausXML(String(leser.result)); }
      } catch (err) {
        status("Datei konnte nicht gelesen werden: " + err.message, 7000);
        return;
      }
      if (pts.length < 2) {
        // Ein Strecken-Export ist ebenfalls JSON und wird hier naheliegenderweise
        // abgelegt – er gehört aber auf die Streckenliste, wo er auch Posten und
        // Items mitbringt. Ohne den Hinweis sucht man den Fehler in der Datei.
        status(roh && roh.format === "fahrradpruefung-strecke"
          ? "Das ist ein Strecken-Export. Den liest du unter „Strecken“ mit „Strecke importieren“ ein – dabei kommen auch Posten und Items mit."
          : "In der Datei wurde keine Linie gefunden.", 8000);
        return;
      }
      zustand.streckenmodus = "import";
      zustand.spur = pts; zustand.linie = pts; zustand.wegpunkte = [];
      geaendert();
      zeichnen();
      karte.fitBounds(L.latLngBounds(pts), { padding: [30, 30], maxZoom: Q.kacheln[quelle].maxNativeZoom });
      status(pts.length + " Punkte übernommen (" + laengeText(laenge(pts)) + ").", 5000);
    };
    leser.readAsText(f);
  });

  // ------------------------------------------------------------------ Ortssuche

  $("suche").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("suchtext").value.trim();
    if (!q) return;
    try {
      const r = await fetch(Q.ortssuche + "?format=json&limit=1&countrycodes=de&q=" + encodeURIComponent(q));
      const j = await r.json();
      if (j && j[0]) karte.setView([parseFloat(j[0].lat), parseFloat(j[0].lon)], 17);
      else status("Nichts gefunden.", 4000);
    } catch (err) {
      status("Die Ortssuche ist gerade nicht erreichbar.", 5000);
    }
  });

  // ------------------------------------------------------------------ Speichern

  $("speichern-form").addEventListener("submit", () => {
    const verlauf = zustand.linie.length >= 2
      ? { modus: zustand.streckenmodus, wegpunkte: zustand.streckenmodus === "route" ? zustand.wegpunkte : [], linie: zustand.linie }
      : null;
    $("feld-verlauf").value = JSON.stringify(verlauf);
    const orte = {};
    for (const p of zustand.posten) orte[p.id] = p.ort;
    $("feld-orte").value = JSON.stringify(orte);
    zustand.geaendert = false;
  });

  window.addEventListener("beforeunload", (e) => {
    if (zustand.geaendert) { e.preventDefault(); e.returnValue = ""; }
  });

  // ------------------------------------------------------------------ Export

  function kachelUrl(z, x, y) {
    const s = Q.kacheln[quelle];
    const subs = s.subs.length ? s.subs : [""];
    return s.url.replace("{s}", subs[Math.abs(x + y) % subs.length]).replace("{z}", z).replace("{x}", x).replace("{y}", y);
  }

  function kachelLaden(url) {
    return new Promise((fertig) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        try {
          const c = document.createElement("canvas");
          c.width = 256; c.height = 256;
          c.getContext("2d").drawImage(img, 0, 0, 256, 256);
          fertig(c.toDataURL("image/png"));
        } catch (e) { fertig(null); }
      };
      img.onerror = () => fertig(null);
      img.src = url;
    });
  }

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  function massstab(maxMeter) {
    let best = 10;
    for (const s of [10, 20, 25, 50, 100, 150, 200, 250, 500, 750, 1000, 1500, 2000, 3000, 5000]) if (s <= maxMeter) best = s;
    return best;
  }

  async function svgBauen() {
    const f = $("opt-2x").checked ? 2 : 1;
    const grau = $("opt-grau").checked;
    const legende = $("opt-legende").checked;
    const mitPosten = $("opt-posten").checked;
    const groesse = karte.getSize();
    const W = Math.round(groesse.x * f), H = Math.round(groesse.y * f);
    const z = Math.min(Q.kacheln[quelle].maxNativeZoom, karte.getZoom() + (f === 2 ? 1 : 0));
    const nw = karte.project(karte.getBounds().getNorthWest(), z);
    const se = karte.project(karte.getBounds().getSouthEast(), z);
    const kx = W / (se.x - nw.x), ky = H / (se.y - nw.y);
    const proj = (ll) => { const p = karte.project(L.latLng(ll[0], ll[1]), z); return [(p.x - nw.x) * kx, (p.y - nw.y) * ky]; };

    const auftraege = [];
    const max = Math.pow(2, z) - 1;
    for (let tx = Math.floor(nw.x / 256); tx <= Math.floor(se.x / 256); tx++) {
      for (let ty = Math.floor(nw.y / 256); ty <= Math.floor(se.y / 256); ty++) {
        if (ty < 0 || ty > max) continue;
        auftraege.push({ url: kachelUrl(z, ((tx % (max + 1)) + max + 1) % (max + 1), ty), x: (tx * 256 - nw.x) * kx, y: (ty * 256 - nw.y) * ky });
      }
    }
    let fertig = 0;
    status("Kartenbilder werden geladen (0/" + auftraege.length + ") …");
    const kacheln = await Promise.all(auftraege.map(async (a) => {
      a.daten = await kachelLaden(a.url);
      status("Kartenbilder werden geladen (" + ++fertig + "/" + auftraege.length + ") …");
      return a;
    }));
    if (kacheln.every((k) => !k.daten)) throw new Error("Der Kartenserver hat kein Bild geliefert. Bitte einen anderen Kartenstil wählen.");

    const nennung = Q.kacheln[quelle].attr;
    const t = [];
    t.push(`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
    t.push(`<title>${esc(daten.strecke.name)}</title><desc>${esc(nennung)}</desc>`);
    t.push(`<defs><clipPath id="ausschnitt"><rect x="0" y="0" width="${W}" height="${H}"/></clipPath>`);
    if (grau) t.push('<filter id="grau"><feColorMatrix type="saturate" values="0"/></filter>');
    t.push(`</defs><rect x="0" y="0" width="${W}" height="${H}" fill="#f2efe9"/>`);
    t.push(`<g clip-path="url(#ausschnitt)"${grau ? ' filter="url(#grau)"' : ""}>`);
    for (const k of kacheln) {
      if (k.daten) t.push(`<image x="${k.x.toFixed(2)}" y="${k.y.toFixed(2)}" width="${(256 * kx).toFixed(2)}" height="${(256 * ky).toFixed(2)}" xlink:href="${k.daten}"/>`);
    }
    t.push("</g>");
    if (zustand.linie.length >= 2) {
      const d = zustand.linie.map((p, i) => { const q = proj(p); return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); }).join(" ");
      t.push(`<g clip-path="url(#ausschnitt)" fill="none" stroke-linejoin="round" stroke-linecap="round">`);
      t.push(`<path d="${d}" stroke="#ffffff" stroke-width="${10 * f}" stroke-opacity="0.9"/><path d="${d}" stroke="${LINIENFARBE}" stroke-width="${5 * f}"/>`);
      const a = proj(zustand.linie[0]);
      t.push(`<circle cx="${a[0].toFixed(1)}" cy="${a[1].toFixed(1)}" r="${7 * f}" fill="#ffffff" stroke="${LINIENFARBE}" stroke-width="${3 * f}"/></g>`);
    }
    if (mitPosten) {
      t.push('<g clip-path="url(#ausschnitt)" font-family="Arial, Helvetica, sans-serif" font-weight="700" text-anchor="middle">');
      for (const p of zustand.posten) {
        if (!p.ort) continue;
        const q = proj(p.ort);
        t.push(`<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="${13 * f}" fill="#1a1a1a" stroke="#ffffff" stroke-width="${2.5 * f}"/>`);
        t.push(`<text x="${q[0].toFixed(1)}" y="${(q[1] + 5 * f).toFixed(1)}" font-size="${14 * f}" fill="#ffffff">${p.nummer}</text>`);
      }
      t.push("</g>");
    }
    if (legende) {
      const verortet = zustand.posten.filter((p) => p.ort);
      const zeilen = [daten.strecke.name + " – " + laengeText(laenge(zustand.linie)), ...verortet.map((p) => p.nummer + ". " + p.name)];
      const boxB = Math.max(160, ...zeilen.map((z) => z.length * 7.2 + 40)) * f;
      const boxH = (22 + zeilen.length * 18) * f;
      t.push('<g font-family="Arial, Helvetica, sans-serif">');
      t.push(`<rect x="${16 * f}" y="${16 * f}" width="${boxB.toFixed(0)}" height="${boxH.toFixed(0)}" rx="${6 * f}" fill="#ffffff" fill-opacity="0.93" stroke="#c9cfc9"/>`);
      zeilen.forEach((z, i) => {
        t.push(`<text x="${28 * f}" y="${(36 + i * 18) * f}" font-size="${(i ? 12 : 13) * f}" font-weight="${i ? 400 : 700}" fill="#1c2321">${esc(z)}</text>`);
      });
      t.push("</g>");
      const mProPx = 156543.03392 * Math.cos(karte.getCenter().lat * Math.PI / 180) / Math.pow(2, z) / kx;
      const ziel = massstab(mProPx * W * 0.28), px = ziel / mProPx, by = H - 18 * f, bx = 16 * f;
      t.push(`<g font-family="Arial, Helvetica, sans-serif"><rect x="${bx - 6 * f}" y="${by - 16 * f}" width="${px + 12 * f}" height="${26 * f}" rx="${4 * f}" fill="#ffffff" fill-opacity="0.85"/>`);
      t.push(`<line x1="${bx}" y1="${by}" x2="${bx + px}" y2="${by}" stroke="#1c2321" stroke-width="${2.5 * f}"/>`);
      t.push(`<text x="${bx}" y="${by - 7 * f}" font-size="${11 * f}" fill="#1c2321">${ziel >= 1000 ? ziel / 1000 + " km" : ziel + " m"}</text></g>`);
    }
    t.push(`<text x="${W - 10 * f}" y="${H - 8 * f}" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="${11 * f}" fill="#333333">${esc(nennung)}</text></svg>`);
    status(null);
    return { svg: t.join(""), W, H };
  }

  function dateiname() {
    return (daten.strecke.name.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "strecke");
  }
  function herunterladen(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1000);
  }

  $("export-svg").addEventListener("click", async () => {
    try {
      const r = await svgBauen();
      herunterladen(new Blob([r.svg], { type: "image/svg+xml;charset=utf-8" }), dateiname() + ".svg");
    } catch (e) { status("Export fehlgeschlagen: " + e.message, 8000); }
  });
  $("export-png").addEventListener("click", async () => {
    try {
      const r = await svgBauen();
      const url = URL.createObjectURL(new Blob([r.svg], { type: "image/svg+xml;charset=utf-8" }));
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = r.W; c.height = r.H;
        c.getContext("2d").drawImage(img, 0, 0);
        c.toBlob((b) => { herunterladen(b, dateiname() + ".png"); URL.revokeObjectURL(url); }, "image/png");
      };
      img.onerror = () => status("PNG-Export fehlgeschlagen. Das SVG funktioniert trotzdem.", 8000);
      img.src = url;
    } catch (e) { status("Export fehlgeschlagen: " + e.message, 8000); }
  });
  $("opt-grau").addEventListener("change", (e) => document.body.classList.toggle("graustufen", e.target.checked));

  // ------------------------------------------------------------------ Start

  quelleAnwenden();
  routingHinweis();
  postenListe();
  andereListe();
  zeichnen();

  const alle = [...zustand.linie, ...zustand.posten.filter((p) => p.ort).map((p) => p.ort)];
  const vergleich = daten.andere.flatMap((s) => s.linie);
  if (alle.length > 1) karte.fitBounds(L.latLngBounds(alle), { padding: [40, 40], maxZoom: Q.kacheln[quelle].maxNativeZoom });
  else if (alle.length === 1) karte.setView(alle[0], 17);
  else if (vergleich.length > 1) karte.fitBounds(L.latLngBounds(vergleich), { padding: [40, 40], maxZoom: Q.kacheln[quelle].maxNativeZoom });
  else {
    karte.setView(DEUTSCHLAND[0], DEUTSCHLAND[1]);
    status("Suche links den Ort der Schule, dann Posten setzen und die Strecke klicken.", 10000);
  }
})();
