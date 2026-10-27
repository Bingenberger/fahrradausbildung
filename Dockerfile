# Fahrradprüfung – Anwendungs-Image (Python 3.12, WeasyPrint)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    XDG_CACHE_HOME=/var/cache/fahrrad

# WeasyPrint braucht Pango/HarfBuzz; DejaVu ist die Schrift der PDF-Vorlagen.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app
# Abhängigkeiten zuerst – diese Schicht bleibt bei Codeänderungen im Cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY docker/start.sh /usr/local/bin/start.sh

RUN useradd --system --uid 10001 --no-create-home fahrrad \
 && mkdir -p /var/cache/fahrrad && chown fahrrad /var/cache/fahrrad
USER fahrrad

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/gesund', timeout=4).status == 200 else 1)"

CMD ["/usr/local/bin/start.sh"]
