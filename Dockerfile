# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY nazar/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy app source
COPY nazar/ ./nazar/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Create data dir (used for campaign knowledge files; DB is Postgres in prod)
RUN mkdir -p /app/nazar/data/campaign_knowledge

# Expose port
EXPOSE 8002

# Run migrations then start the API server
CMD alembic upgrade head && \
    uvicorn nazar.server:app \
        --host 0.0.0.0 \
        --port 8002 \
        --workers 1 \
        --log-level info
