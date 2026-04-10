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

## Architecture

```
Dashboard (business team)
  → compose/send message
    → WhatsApp Cloud API → customer receives on WhatsApp
      → customer replies → webhook → server.py
        → AI generates contextual reply using customer memory
          → sends reply + logs conversation + updates pipeline
            → appears in dashboard in real-time
```

## Quick Start

```bash
cd nazar
cp .env.template .env
# Fill in your WhatsApp Business API credentials

pip install fastapi uvicorn httpx chromadb pydantic cryptography python-dotenv

python server.py
# Dashboard: http://localhost:8001
```

## Project Structure

```
nazar/
├── server.py                 ← FastAPI: webhook + REST API + serve frontend
├── .env.template             ← Environment variable template
├── agent/
│   └── SOUL.md               ← Bot persona: structured sales assistant
├── core/
│   ├── llm_router.py         ← Multi-provider LLM with failover
│   ├── transcription.py      ← Voice note transcription (Groq Whisper)
│   ├── encryption.py         ← Per-contact Fernet encryption
│   ├── contact_manager.py    ← Contacts CRUD, pipeline, CSV import/export
│   ├── customer_memory.py    ← Per-customer ChromaDB vector memory
│   ├── conversation.py       ← Inbound handling + AI reply generation
│   ├── outbound.py           ← Send messages / broadcasts from dashboard
│   ├── template_manager.py   ← Template library, auto-generation, approval tracking
│   └── digest_engine.py      ← Follow-up reminders, scheduled reports
├── frontend/
│   └── index.html            ← Full dashboard (single-file, no build tools)
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
| GET | `/api/contacts` | All contacts |
| POST | `/api/contacts` | Create contact |
| POST | `/api/contacts/import` | CSV import |
| PATCH | `/api/contacts/{id}` | Update contact/stage/tags |
| GET | `/api/contacts/{id}/memory` | Memory summary |
| GET | `/api/pipeline` | Contacts by stage with deal values |
| GET | `/api/followups` | Pending follow-ups |
| POST | `/api/broadcasts` | Send to segment |
| GET | `/api/templates` | Template library |
| POST | `/api/templates` | Create template |
| GET | `/api/team` | Team members |
| GET/PUT | `/api/config` | Bot configuration |
| POST | `/api/kb/upload` | Upload knowledge base docs |
| GET | `/` | Serve dashboard |

Auth: `X-Nazar-Key` header for MVP.

## Meta AI Chatbot Compliance

Meta banned general-purpose AI chatbots on WhatsApp (Jan 2026). Nazar is **compliant** because it's a structured sales assistant — not open-ended chat. It responds about specific products/services, handles orders, manages follow-ups, and knows when to hand off to humans.

## License

Proprietary — All rights reserved.
