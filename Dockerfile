# ── Nazar — Production Dockerfile ──────────────────────────────────────
# Multi-stage build: Node (frontend) → Python (backend + built assets)
# ────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build React dashboard ──────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/dashboard

# Copy package files first (layer-cache friendly)
COPY nazar/dashboard/package*.json ./
RUN npm ci --silent

# Copy source and build
COPY nazar/dashboard/ ./
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────────────
FROM python:3.11-slim

# Avoid writing .pyc files, enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    PORT=8001

WORKDIR /app

# Install OS-level dependencies (for chromadb / crypto)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY nazar/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY nazar/ ./

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/dashboard/dist ./dashboard/dist

# Create data directory (will be overridden by volume mount in production)
RUN mkdir -p ./data/auth ./data/contacts ./data/handoffs \
    ./data/billing ./data/analytics ./data/usage \
    ./data/campaign_kb ./data/onboarding

# Non-root user for security
RUN useradd --create-home --shell /bin/bash nazar && \
    chown -R nazar:nazar /app
USER nazar

EXPOSE $PORT

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["python3", "server.py"]
