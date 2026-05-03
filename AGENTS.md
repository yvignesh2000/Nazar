# Agent Instructions

This is **Nazar** — a WhatsApp campaign + conversation platform with AI-assisted reply drafting, knowledge-base grounding, and a React dashboard.

**Read `README.md` first** for full setup, architecture, and run instructions.

## Quick orientation

- **Backend**: FastAPI, entry point `nazar/server.py`, runs on port `8000`.
- **Frontend**: React + Vite in `nazar/dashboard/`, builds to `nazar/dashboard/dist/` (served by FastAPI in production).
- **Core logic**: `nazar/core/`
  - `channel.py` — channel abstraction (WhatsApp, etc.)
  - `conversation.py` — inbound message handling + AI drafting
  - `outbound.py` — campaign send pipeline
  - `kb_store.py` / `knowledge_base.py` — Chroma-backed RAG
  - `templates.py` — message templates
  - `analytics.py` — campaign metrics
- **Tests**: `nazar/tests/` — run with `pytest` from `nazar/`.
- **Demo tooling**: `nazar/seed_demo.py`, `nazar/demo.sh`, `nazar/reset_demo.sh`.
- **Docs**: `docs/`, `nazar/docs/`, `PRODUCT_ANALYSIS.md`, `IMPLEMENTATION_PLAN.md`.

## Run locally

```bash
# Backend
cp .env.template .env       # fill in keys
pip install -r requirements.txt
python -m nazar.server      # http://localhost:8000

# Frontend (separate terminal)
cd nazar/dashboard
npm install
npm run dev                 # http://localhost:5173
```

See `README.md` → "Quick Start" for the full flow including seeding demo data.

## Conventions & guardrails

- **Never commit**: `.env`, `nazar/nazar.db`, `nazar/data/*.db`, `nazar/data/kb/vectors/`, `nazar/data/.chroma_health/`, `*.bak`. All covered by `.gitignore`.
- `nazar/data/kb/docs.json` and `nazar/data/kb/raw/*` are **generated caches** from KB ingestion — do not hand-edit; re-run ingestion instead.
- The source-of-truth KB content is `nazar/data/kb/knowledge_base.txt`.
- DB schema bootstraps automatically via `init_db()` on first server start.
- Chroma vector store auto-creates `data/kb/vectors/` on first write — no manual setup needed.

## Branch

Active development branch: `feature/react-frontend`. Main is older.
