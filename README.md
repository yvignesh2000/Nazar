# 🧿 Nazar — AI-Native WhatsApp CRM

**The only WhatsApp Business tool with per-customer memory.**

Every competitor (WATI, Interakt, AiSensy, Gallabox...) is a UI wrapper around WhatsApp Business API. Every conversation starts fresh. Nazar remembers everything.

## What Makes Nazar Different

| Feature | Competitors | Nazar |
|---|---|---|
| Customer Memory | ❌ Zero | ✅ Per-customer vector memory across all time |
| CRM Pipeline | ❌ Chat inbox only | ✅ Full pipeline: New → Qualified → Proposal → Closed |
| Broadcast Replies | ❌ Manual handling | ✅ AI handles reply threads using customer memory |
| Pricing | ❌ Hidden markups, per-agent fees | ✅ Flat INR monthly. Zero per-message markup |
| AI Compliance | ❌ Generic chatbots (banned Jan 2026) | ✅ Structured sales assistant (compliant) |

## Reply Ownership Model

Nazar now supports reply ownership by use case. This means you can configure who should handle replies for different workflows:

- `Bot first`: AI replies automatically unless a handoff trigger fires
- `Human first`: reply goes to the human queue first
- `Human with AI assist`: AI drafts a response, but a human owns the conversation
- `Manual only`: no bot reply is sent; the conversation is routed to a human queue

Example:
- Broadcast campaign replies can be bot-handled
- Pricing negotiations can go straight to humans
- Complaints can be routed to a support queue

## Architecture

```
Dashboard (business team)
  → compose/send message
    → WhatsApp Cloud API → customer receives on WhatsApp
      → customer replies → webhook → server.py
        → save inbound event + queue job
          → worker.py processes AI, transcription, broadcasts, and follow-up jobs
            → sends reply + logs conversation + updates pipeline
              → appears in dashboard in real-time
```

## Quick Start

```bash
cd nazar
cp .env.template .env
# Fill in your WhatsApp Business API credentials

pip install -r requirements.txt

# Local dev shortcut only if you do not want to run migrations yet
export NAZAR_ALLOW_SCHEMA_CREATE=1
python server.py

# Migration-first flow (recommended)
cd ..
alembic upgrade head
cd nazar
python server.py

# Optional worker for queued broadcasts
python worker.py
```

Database:
- Defaults to local SQLite at `nazar/data/nazar.db`
- Set `DATABASE_URL` to Postgres for a real multi-instance deployment
- The app now expects a migration-managed schema by default
- `NAZAR_ALLOW_SCHEMA_CREATE=1` is a local bootstrap fallback, not the long-term production path
- If legacy file-based contacts exist locally, they are imported into the database on first boot

## Project Structure

```
nazar/
├── server.py                 ← FastAPI: webhook + REST API + serve frontend
├── worker.py                 ← Background worker for queued jobs
├── .env.template             ← Environment variable template
├── agent/
│   └── SOUL.md               ← Bot persona: structured sales assistant
├── core/
│   ├── analytics_store.py    ← Inbox/team operational analytics
│   ├── auth_store.py         ← Session auth + workspace roles
│   ├── db.py                 ← SQLAlchemy models + DB bootstrap
│   ├── job_queue.py          ← Persistent background job queue
│   ├── policy_store.py       ← Reply ownership policies by use case
│   ├── llm_router.py         ← Multi-provider LLM with failover
│   ├── transcription.py      ← Voice note transcription (Groq Whisper)
│   ├── encryption.py         ← Per-contact Fernet encryption
│   ├── contact_manager.py    ← Contacts CRUD + conversation-first inbox state
│   ├── customer_memory.py    ← Per-customer ChromaDB vector memory
│   ├── conversation.py       ← Inbound handling + AI reply generation
│   ├── outbound.py           ← Send messages / broadcasts from dashboard
│   ├── template_manager.py   ← Template library, approval tracking
│   ├── workspace_store.py    ← Workspace config + team memberships
│   └── digest_engine.py      ← Follow-up reminders, scheduled reports
├── frontend/
│   └── index.html            ← Full dashboard (single-file, no build tools)
├── alembic/
│   └── versions/             ← Database migrations
└── data/
    ├── config.json            ← Bot configuration
    ├── knowledge_base.txt     ← Business knowledge base
    └── contacts/              ← Encrypted per-contact data + ChromaDB
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/overview` | Dashboard stats |
| GET | `/api/activity` | Live activity feed |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}` | Full message history |
| POST | `/api/conversations/{id}/send` | Send message from dashboard |
| POST | `/api/conversations/{id}/handover` | Toggle bot/human mode |
| POST | `/api/conversations/{id}/assign` | Assign or unassign owner |
| POST | `/api/conversations/{id}/status` | Mark open / needs reply / snoozed / closed |
| POST | `/api/conversations/{id}/ai-reply` | Queue AI reply suggestion |
| POST | `/api/conversations/{id}/use-case` | Change conversation workflow / reply routing |
| GET | `/api/contacts` | All contacts |
| POST | `/api/contacts` | Create contact |
| POST | `/api/contacts/import` | CSV import |
| PATCH | `/api/contacts/{id}` | Update contact/stage/tags |
| GET | `/api/contacts/{id}/notes` | Internal notes |
| POST | `/api/contacts/{id}/notes` | Add internal note |
| GET | `/api/contacts/{id}/memory` | Memory summary |
| POST | `/api/contacts/{id}/followup-draft` | Queue AI follow-up draft |
| POST | `/api/contacts/{id}/summary/refresh` | Queue AI customer summary |
| GET | `/api/pipeline` | Contacts by stage with deal values |
| GET | `/api/followups` | Pending follow-ups |
| POST | `/api/broadcasts` | Queue segment broadcast |
| GET | `/api/jobs` | Background job list |
| GET | `/api/jobs/{id}` | Background job status |
| GET | `/api/reply-policies` | List reply ownership policies |
| PUT | `/api/reply-policies/{key}` | Update who owns replies for a use case |
| GET | `/api/templates` | Template library |
| POST | `/api/templates` | Create template |
| GET | `/api/team` | Team members |
| GET/PUT | `/api/config` | Bot configuration |
| POST | `/api/kb/upload` | Upload knowledge base docs |
| GET | `/api/analytics/inbox` | Team inbox analytics |
| GET | `/` | Serve dashboard |

Auth:
- UI now boots a bearer session through `/api/auth/login`
- `Authorization: Bearer <token>` is the primary mode
- `X-Nazar-Key` still exists as a transitional fallback for local/dev compatibility

Async processing:
- Inbound WhatsApp text messages are now saved immediately and processed through the job queue
- Voice notes are queued for transcription and reply generation in the worker
- AI reply drafts, follow-up drafts, and contact summaries are also queued jobs
- Reply ownership is enforced in the worker using the configured use-case policy

## Meta AI Chatbot Compliance

Meta banned general-purpose AI chatbots on WhatsApp (Jan 2026). Nazar is **compliant** because it's a structured sales assistant — not open-ended chat. It responds about specific products/services, handles orders, manages follow-ups, and knows when to hand off to humans.

## License

Proprietary — All rights reserved.
