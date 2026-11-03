FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH XDG_CACHE_HOME=/tmp/fahrrad-cache UV_CACHE_DIR=/tmp/uv-cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.6@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && rm -rf /tmp/uv-cache
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY docker/start.sh /usr/local/bin/start.sh
RUN chmod 0755 /usr/local/bin/start.sh \
    && groupadd --gid 10001 fahrrad && useradd --uid 10001 --gid 10001 --no-create-home fahrrad \
    && mkdir -p /vorlagen && chown 10001:10001 /vorlagen && chmod 700 /vorlagen
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=4s --start-period=10s --retries=12 \
 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=3)"
CMD ["/usr/local/bin/start.sh"]

FROM runtime AS tests
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libzbar0 && rm -rf /var/lib/apt/lists/*
RUN uv sync --frozen --no-install-project && rm -rf /tmp/uv-cache
COPY tests ./tests
COPY contract_tests ./contract_tests
COPY .env.example docker-compose.yml ./
USER 10001:10001

FROM tests AS browser-tests
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN python -m playwright install --with-deps chromium webkit
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
USER 10001:10001
