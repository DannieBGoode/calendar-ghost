# The Web UI bundle is plain JavaScript and CSS, the same for every target platform, so it is built
# once on the build machine's own platform. Emulating npm for arm64 is slow and can stall.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web-builder

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
ARG CALENDAR_GHOST_SOURCE_URL
ENV CALENDAR_GHOST_SOURCE_URL=${CALENDAR_GHOST_SOURCE_URL}
RUN npm run build:bundle

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CALENDAR_SYNC_DATABASE_PATH=/data/calendar-sync.db

RUN addgroup --system calendar-sync && adduser --system --ingroup calendar-sync calendar-sync
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY --from=web-builder /web/dist ./src/calendar_sync/interfaces/api/static
RUN pip install --no-cache-dir .

RUN mkdir -p /data && chown calendar-sync:calendar-sync /data
USER calendar-sync

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "calendar_sync.interfaces.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
