# freelance-parser image. Built by GitHub Actions (.github/workflows/image.yml)
# into ghcr.io/kamabyte/freelance-parser, run e.g. by Dokploy (see DEPLOY.md).
#
# State (SQLite DB with seen projects and your decisions) lives in /data —
# mount a volume there. A config.yaml / profile.md dropped into /data overrides
# the ones baked into the image. Secrets come from env vars (see .env.example).

# --- Dependencies ------------------------------------------------------------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer stays cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md config.yaml profile.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# --- Runtime -----------------------------------------------------------------
FROM python:3.12-slim
# Not root. Fixed uid/gid so a bind-mounted /data can be chowned to match.
RUN groupadd --system --gid 10001 bot \
    && useradd --system --uid 10001 --gid bot --no-create-home bot \
    && mkdir /data && chown bot:bot /data
WORKDIR /app
COPY --from=build --chown=bot:bot /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data
VOLUME /data
USER bot
# Long polling: no ports, no domain. Every finished feed poll touches the
# heartbeat file; if it's older than 10 minutes, the poll loop is stuck.
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,time; sys.exit(time.time() - os.path.getmtime('/tmp/freelance-parser.heartbeat') > 600)"
STOPSIGNAL SIGTERM
CMD ["freelance-parser"]
