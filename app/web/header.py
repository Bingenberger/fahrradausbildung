"""Sicherheits-Header für alle Antworten (Spezifikation 9).

Eine einzige Ausnahme von der strengen CSP: Die Kartenseite der Streckenplanung
(``request.state.csp = "karte"``) darf Kacheln und Routing von den Servern in
``app/kartenquellen.py`` laden – und nur von diesen. Auch dort gilt: kein
``unsafe-inline``, Skripte nur vom eigenen Server.
"""

from starlette.middleware.base import BaseHTTPMiddleware

from app.kartenquellen import bildquellen, verbindungsziele

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; font-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)

KARTEN_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    f"img-src 'self' data: blob: {' '.join(bildquellen())}; "
    f"connect-src 'self' {' '.join(verbindungsziele())}; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


class Sicherheitsheader(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool = True, cache: str | None = None) -> None:
        super().__init__(app)
        self.hsts = hsts
        self.cache = cache

    async def dispatch(self, request, call_next):
        antwort = await call_next(request)
        h = antwort.headers
        karte = getattr(request.state, "csp", None) == "karte"
        h["Content-Security-Policy"] = KARTEN_CSP if karte else CSP
        h["X-Content-Type-Options"] = "nosniff"
        # Kachelserver (u. a. tile.openstreetmap.org) verlangen einen Referer;
        # die Kartenseite verrät dabei nur den Hostnamen, keinen Pfad.
        h["Referrer-Policy"] = "strict-origin-when-cross-origin" if karte else "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if self.hsts:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if self.cache and "Cache-Control" not in h:
            h["Cache-Control"] = self.cache
        return antwort
