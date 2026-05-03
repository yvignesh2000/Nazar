# ──────────────────────────────────────────────────────────────────────
#  Nazar — Production Dockerfile (multi-stage)
#  Stage 1: build the React dashboard
#  Stage 2: install Python deps and copy app
# ──────────────────────────────────────────────────────────────────────

# ── Stage 1: dashboard build ─────────────────────────────────────────
FROM node:20-alpine AS dashboard-builder

WORKDIR /build
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY dashboard/ ./
RUN npm run build


# ── Stage 2: Python runtime ──────────────────────────────────────────
FROM python:3.11-slim

# System deps for sqlite/pdfplumber/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libsqlite3-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the entire app
COPY . .

# Drop the un-built dashboard sources and replace with the compiled bundle
RUN rm -rf /app/dashboard/dist /app/dashboard/node_modules
COPY --from=dashboard-builder /build/dist /app/dashboard/dist

# Persistent data directory
RUN mkdir -p /app/data && chmod 755 /app/data

EXPOSE 8001

# Healthcheck (server.py exposes /api/health or root)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/api/health || curl -f http://localhost:8001/ || exit 1

CMD ["python3", "server.py"]
