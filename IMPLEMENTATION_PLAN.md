# Nazar — Production Hardening Implementation Plan

**Date:** June 2025  
**Audience:** Engineering Team  
**Priority System:** P0 (blocks launch) → P1 (week 1 post-launch) → P2 (month 1) → P3 (quarter 1)

---

## Table of Contents

1. [Architecture Overview & Current State](#1-architecture-overview--current-state)
2. [P0 — Storage Layer: Replace JSON Files with SQLite](#2-p0--storage-layer-replace-json-files-with-sqlite)
3. [P0 — Real-time Communication: WebSocket Layer](#3-p0--real-time-communication-websocket-layer)
4. [P0 — WhatsApp Template Messages in Campaigns](#4-p0--whatsapp-template-messages-in-campaigns)
5. [P0 — Webhook Security: Mandatory Signature Verification](#5-p0--webhook-security-mandatory-signature-verification)
6. [P1 — Background Job Queue for Campaign Sends](#6-p1--background-job-queue-for-campaign-sends)
7. [P1 — Agent Assignment & Conversation Routing](#7-p1--agent-assignment--conversation-routing)
8. [P1 — Opt-out / Unsubscribe Handling](#8-p1--opt-out--unsubscribe-handling)
9. [P1 — Campaign Scheduling & Drip Campaigns](#9-p1--campaign-scheduling--drip-campaigns)
10. [P1 — WhatsApp API Rate Limiting](#10-p1--whatsapp-api-rate-limiting)
11. [P2 — Media Message Support (Inbound + Outbound)](#11-p2--media-message-support-inbound--outbound)
12. [P2 — Contact Segmentation Engine](#12-p2--contact-segmentation-engine)
13. [P2 — Structured Knowledge Base with RAG](#13-p2--structured-knowledge-base-with-rag)
14. [P2 — Outbound Webhooks & CRM Integrations](#14-p2--outbound-webhooks--crm-integrations)
15. [P2 — Campaign Analytics Enhancement](#15-p2--campaign-analytics-enhancement)
16. [P3 — API Input Validation with Pydantic](#16-p3--api-input-validation-with-pydantic)
17. [P3 — Pagination Across All List Endpoints](#17-p3--pagination-across-all-list-endpoints)
18. [P3 — Session Token Revocation](#18-p3--session-token-revocation)
19. [P3 — Audit Log System](#19-p3--audit-log-system)
20. [P3 — Memory Decay & Archival](#20-p3--memory-decay--archival)
21. [P3 — Docker & Deployment Configuration](#21-p3--docker--deployment-configuration)
22. [P3 — Frontend Error Boundaries & Testing](#22-p3--frontend-error-boundaries--testing)
23. [P3 — Branding Cleanup & i18n Prep](#23-p3--branding-cleanup--i18n-prep)
24. [P3 — Health Check Enhancements](#24-p3--health-check-enhancements)
25. [P3 — Currency Configuration](#25-p3--currency-configuration)
26. [P1 — Multi-Channel Support (Multiple Phone Numbers)](#26-p1--multi-channel-support-multiple-phone-numbers)
27. [Test Plan](#27-test-plan)
28. [Migration Strategy](#28-migration-strategy)
29. [Rollout Sequence](#29-rollout-sequence)

---

## 1. Architecture Overview & Current State

### Tech Stack
- **Backend:** Python 3.11+, FastAPI, uvicorn (single-process)
- **Frontend:** React 19, Vite 8, react-router-dom 6
- **AI/LLM:** Anthropic Claude (Sonnet/Haiku), OpenRouter fallback, Google Gemini fallback
- **Vector DB:** ChromaDB (local, per-contact collections)
- **Storage:** JSON flat files + encrypted profile/conversation JSONL files
- **Encryption:** HKDF-derived per-contact Fernet keys (via `core/encryption.py`)

### Current Module Map

| Module | File | Purpose |
|--------|------|---------|
| Contact Manager | `core/contact_manager.py` | CRM CRUD, pipeline, scoring, conversations. Encrypted at rest. |
| Conversation Engine | `core/conversation.py` | Inbound handling, AI reply generation, system prompt building |
| Customer Memory | `core/customer_memory.py` | ChromaDB vector memory, signal extraction, semantic search |
| LLM Router | `core/llm_router.py` | Multi-provider failover (Anthropic → OpenRouter → Gemini) |
| Handoff Manager | `core/handoff_manager.py` | AI-to-human handoff lifecycle, auto-resume, queue |
| Reply Mode | `core/reply_mode.py` | Per-contact/campaign reply modes (auto_ai, human_only, ai_draft) |
| Outbound | `core/outbound.py` | Campaigns, broadcasts, message personalization |
| Template Manager | `core/template_manager.py` | WhatsApp template CRUD, rendering, suggestions |
| Auth Manager | `core/auth_manager.py` | Workspaces, users, HMAC tokens, RBAC, invitations |
| Billing | `core/billing.py` | Subscriptions, plan limits, usage tracking |
| Analytics | `core/analytics.py` | Event logging, conversation/pipeline/campaign analytics |
| Usage Tracker | `core/usage_tracker.py` | LLM token/cost tracking per provider |
| Digest Engine | `core/digest_engine.py` | Daily summary generation |
| Onboarding | `core/onboarding.py` | Setup wizard state machine |
| Encryption | `core/encryption.py` | HKDF key derivation, Fernet encrypt/decrypt |
| Transcription | `core/transcription.py` | Groq Whisper voice note transcription |
| API Server | `server.py` | FastAPI app, all REST endpoints, webhook handler |

### Current Data Directory Layout

```
data/
├── contacts/                  # Per-contact encrypted directories
│   ├── {contact_id}/
│   │   ├── profile.json.enc   # Encrypted contact profile
│   │   └── conversations/
│   │       └── YYYY-MM-DD.jsonl.enc  # Encrypted daily messages
│   └── .phone_index.json      # Plaintext contact_id → phone mapping
├── auth/
│   ├── users.json
│   └── workspaces.json
├── billing/
│   └── subscriptions.json
├── handoffs/
│   ├── state.json             # Current handoff states
│   └── history.jsonl          # Handoff audit trail
├── analytics/
│   └── YYYY-MM-DD.jsonl       # Daily event logs
├── usage/
│   └── YYYY-MM-DD.jsonl       # Daily LLM usage logs
├── onboarding/
│   └── {workspace_id}.json
├── campaigns.json             # All campaigns
├── templates.json             # WhatsApp templates
├── config.json                # Global config
├── knowledge_base.txt         # Global KB (single file)
├── reply_modes.json           # Per-contact reply mode overrides
├── campaign_contacts.json     # Contact → campaign associations
├── ai_drafts.json             # Pending AI drafts
├── campaign_kb/               # Per-campaign knowledge bases
│   └── {campaign_id}.txt
└── .token_secret              # HMAC signing secret
```

---

## 2. P0 — Storage Layer: Replace JSON Files with SQLite

### Why This Blocks Launch

Every module currently does `json.loads(path.read_text())` → mutate → `json.dumps(path.write_text())`. This causes:

1. **Race conditions** — Two webhook requests hitting simultaneously corrupt data. The `fcntl.flock()` in `contact_manager.py` and `reply_mode.py` is inconsistent — `campaigns.json`, `ai_drafts.json`, `campaign_contacts.json` don't use locking.
2. **O(n) scans** — `list_contacts()` iterates ALL directories and decrypts ALL profiles. At 10K contacts, this is 10K file reads + 10K decryptions per API call.
3. **No transactions** — A crash mid-write = corrupted JSON = data loss.
4. **No indexing** — Can't efficiently query "all contacts in stage=Negotiation with score>70".

### Implementation

#### 2.1 Add SQLAlchemy + aiosqlite to `requirements.txt`

```
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.19.0
alembic>=1.12.0
```

#### 2.2 Create `core/database.py`

```python
"""
Nazar — Database Layer

SQLite with SQLAlchemy async. Replaces all JSON flat-file storage.
Contact profile content and conversation messages remain encrypted at rest
using per-contact Fernet keys (same HKDF derivation as before).

The database stores encrypted blobs, NOT plaintext PII.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, func
)
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "nazar.db"

engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), nullable=True)
    stage: Mapped[str] = mapped_column(String(50), default="New", index=True)
    lead_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    deal_value: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(100), nullable=True)
    tags: Mapped[dict] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Encrypted profile blob (for PII fields like email, address)
    encrypted_profile: Mapped[bytes] = mapped_column(nullable=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    last_contact_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_contacts_stage_score", "stage", "lead_score"),
        Index("ix_contacts_opt_out", "opt_out"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # "inbound" | "outbound"
    content_type: Mapped[str] = mapped_column(String(20), default="text")  # text, image, document, audio, template
    # Encrypted message body
    encrypted_content: Mapped[bytes] = mapped_column()
    wa_message_id: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=True)  # sent, delivered, read, failed
    media_url: Mapped[str] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)

    __table_args__ = (
        Index("ix_messages_contact_ts", "contact_id", "timestamp"),
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    template_id: Mapped[str] = mapped_column(String(36), nullable=True)
    filter_stage: Mapped[str] = mapped_column(String(50), nullable=True)
    filter_tag: Mapped[str] = mapped_column(String(100), nullable=True)
    reply_mode: Mapped[str] = mapped_column(String(20), default="auto_ai")
    knowledge_base: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft, scheduled, sending, sent, failed
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CampaignContact(Base):
    """Track which contacts received which campaign."""
    __tablename__ = "campaign_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"), index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, sent, delivered, read, replied, failed
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_cc_campaign_contact", "campaign_id", "contact_id", unique=True),
    )


class AIDraft(Base):
    __tablename__ = "ai_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=True)
    customer_message: Mapped[str] = mapped_column(Text)
    draft_text: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, edited, rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_drafts_status", "status"),
    )


class HandoffState(Base):
    __tablename__ = "handoff_states"

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), primary_key=True)
    bot_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=True)  # agent user_id


class HandoffEvent(Base):
    __tablename__ = "handoff_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))  # triggered, resumed, human_responded
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(36), nullable=True)  # user_id or "system"
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Tracks all state-changing actions for compliance and debugging."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))  # contact, campaign, draft, config
    resource_id: Mapped[str] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OptOut(Base):
    """Explicit opt-out records for compliance."""
    __tablename__ = "opt_outs"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=True)
    opted_out_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reason: Mapped[str] = mapped_column(String(100), default="STOP keyword")


async def init_db():
    """Create all tables. Call once on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

#### 2.3 Create `core/db_migration.py` — One-time JSON → SQLite migrator

Write a script that:
1. Reads all existing JSON files (`campaigns.json`, `reply_modes.json`, etc.)
2. Iterates `data/contacts/*/profile.json.enc`, decrypts each, inserts into `contacts` table
3. Iterates all `conversations/*.jsonl.enc`, decrypts, inserts into `messages` table
4. Migrates `handoffs/state.json` → `handoff_states` table
5. Migrates `handoffs/history.jsonl` → `handoff_events` table
6. Migrates `ai_drafts.json` → `ai_drafts` table
7. Migrates `campaign_contacts.json` → `campaign_contacts` table

Run this exactly once before switching over. Keep the old data directory as backup.

#### 2.4 Refactor All Modules to Use Database

Each module that currently does `json.loads(path.read_text())` needs an async database version. Approach:

**For `contact_manager.py`:**
- Replace `create_contact()` → `INSERT INTO contacts`
- Replace `list_contacts()` → `SELECT * FROM contacts` (with pagination, filtering)
- Replace `get_contact()` → `SELECT * FROM contacts WHERE id = ?`
- Replace `save_message()` → `INSERT INTO messages`
- Replace `get_conversation_history()` → `SELECT * FROM messages WHERE contact_id = ? ORDER BY timestamp`
- Keep encryption: store `encrypted_content` in `messages` table, `encrypted_profile` for PII in `contacts` table
- The plaintext fields (`name`, `stage`, `score`, `tags`) stay queryable. Only sensitive fields (email, custom notes with PII) go in encrypted blob.

**For `outbound.py`:**
- Replace `_load_campaigns()` / `_save_campaigns()` → `SELECT/INSERT/UPDATE campaigns`
- Replace campaign stats aggregation → SQL `SUM()` queries

**For `reply_mode.py`:**
- Replace `_load_reply_modes()` → `SELECT reply_mode FROM contacts WHERE id = ?` (add `reply_mode` column to `contacts` table)
- Replace `_load_drafts()` → `SELECT * FROM ai_drafts WHERE status = 'pending'`
- Replace `_load_campaign_contacts()` → `SELECT campaign_id FROM campaign_contacts WHERE contact_id = ?`

**For `handoff_manager.py`:**
- Replace `state.json` → `handoff_states` table
- Replace `history.jsonl` → `handoff_events` table

**For `auth_manager.py` and `billing.py`:**
- These can stay as JSON for now (low-volume, rarely concurrent). Migrate in P3.
- Or add `workspaces`, `users`, `subscriptions` tables now if you prefer consistency.

#### 2.5 Acceptance Criteria

- [ ] All existing tests pass with SQLite backend
- [ ] 10,000 contacts load in < 500ms
- [ ] Concurrent webhook requests don't corrupt data (test with `ab -n 100 -c 10`)
- [ ] Migration script successfully imports all existing data
- [ ] Encrypted content in DB is not readable without master secret

---

## 3. P0 — Real-time Communication: WebSocket Layer

### Why This Blocks Launch

The AI Draft workflow (`ai_draft` reply mode) is fundamentally broken without real-time updates. When a customer replies:
1. The AI generates a draft (in `_handle_text_message` → `reply_mode.save_draft()`)
2. The human agent has **no way to know** a draft exists until they manually refresh the page
3. Same problem for new inbound messages, handoff triggers, campaign status updates

### Implementation

#### 3.1 Add WebSocket support to `server.py`

FastAPI natively supports WebSocket. No new dependencies needed.

```python
# server.py — Add WebSocket manager

from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json

class ConnectionManager:
    """Manages active WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Key = workspace_id, Value = list of connected WebSockets

    async def connect(self, websocket: WebSocket, workspace_id: str):
        await websocket.accept()
        if workspace_id not in self.active_connections:
            self.active_connections[workspace_id] = []
        self.active_connections[workspace_id].append(websocket)

    def disconnect(self, websocket: WebSocket, workspace_id: str):
        if workspace_id in self.active_connections:
            self.active_connections[workspace_id] = [
                ws for ws in self.active_connections[workspace_id] if ws != websocket
            ]

    async def broadcast(self, workspace_id: str, event_type: str, data: dict):
        """Send an event to all connected clients in a workspace."""
        message = json.dumps({"type": event_type, "data": data})
        if workspace_id not in self.active_connections:
            return
        dead = []
        for ws in self.active_connections[workspace_id]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active_connections[workspace_id].remove(ws)


ws_manager = ConnectionManager()


@app.websocket("/ws/{workspace_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: str):
    # Authenticate via query param token
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    try:
        ctx = validate_token(token)
    except Exception:
        await websocket.close(code=4003, reason="Invalid token")
        return

    await ws_manager.connect(websocket, workspace_id)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, workspace_id)
```

#### 3.2 Emit events from critical code paths

Add `await ws_manager.broadcast(...)` calls in:

| Location in `server.py` | Event Type | Payload |
|---|---|---|
| `_handle_text_message` — after `save_message()` for inbound | `message:inbound` | `{contact_id, phone, text, timestamp}` |
| `_handle_text_message` — after AI reply sent | `message:outbound` | `{contact_id, text, timestamp}` |
| `_handle_text_message` — after `save_draft()` | `draft:new` | `{contact_id, draft_text, customer_message}` |
| `_handle_text_message` — after handoff triggered | `handoff:triggered` | `{contact_id, reason, category}` |
| `_handle_status_update` — on status changes | `message:status` | `{wa_message_id, status}` |
| `api_send_message` — after human sends | `message:outbound` | `{contact_id, text}` |
| Campaign execution — per contact | `campaign:progress` | `{campaign_id, sent, total, failed}` |
| Draft approved/rejected | `draft:resolved` | `{contact_id, status}` |

#### 3.3 Frontend WebSocket Client

Create `dashboard/src/hooks/useWebSocket.js`:

```javascript
import { useEffect, useRef, useCallback, useState } from 'react';

export function useWebSocket(workspaceId) {
  const wsRef = useRef(null);
  const [lastEvent, setLastEvent] = useState(null);
  const listenersRef = useRef(new Map());

  useEffect(() => {
    if (!workspaceId) return;

    const token = localStorage.getItem('nazar_token');
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/${workspaceId}?token=${token}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        setLastEvent(parsed);
        // Notify all registered listeners
        const handlers = listenersRef.current.get(parsed.type) || [];
        handlers.forEach(fn => fn(parsed.data));
      } catch {}
    };

    ws.onclose = () => {
      // Auto-reconnect after 3 seconds
      setTimeout(() => {
        // Reconnect logic (re-run effect)
      }, 3000);
    };

    // Ping every 30s to keep alive
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      ws.close();
    };
  }, [workspaceId]);

  const subscribe = useCallback((eventType, handler) => {
    if (!listenersRef.current.has(eventType)) {
      listenersRef.current.set(eventType, []);
    }
    listenersRef.current.get(eventType).push(handler);
    return () => {
      const handlers = listenersRef.current.get(eventType) || [];
      listenersRef.current.set(eventType, handlers.filter(fn => fn !== handler));
    };
  }, []);

  return { subscribe, lastEvent };
}
```

#### 3.4 Integrate into `ConversationDetail.jsx`

```javascript
// In ConversationDetail component:
const { subscribe } = useWebSocket(workspaceId);

useEffect(() => {
  const unsub1 = subscribe('message:inbound', (data) => {
    if (data.contact_id === contactId) {
      // Append message to local state — no refetch needed
      setMessages(prev => [...prev, data]);
    }
  });

  const unsub2 = subscribe('draft:new', (data) => {
    if (data.contact_id === contactId) {
      setDraft(data);
    }
  });

  return () => { unsub1(); unsub2(); };
}, [contactId]);
```

#### 3.5 Acceptance Criteria

- [ ] New inbound messages appear in ConversationDetail within 500ms without refresh
- [ ] AI drafts appear as a review panel instantly when generated
- [ ] Handoff alerts show a notification badge on Handoffs sidebar item
- [ ] Campaign progress is live-updated during send
- [ ] Connection auto-reconnects on network drop
- [ ] WebSocket rejects unauthenticated connections (test with no token / expired token)

---

## 4. P0 — WhatsApp Template Messages in Campaigns

### Why This Blocks Launch

WhatsApp Business API **requires** pre-approved template messages to initiate conversations outside the 24-hour session window. If a contact hasn't messaged your business in 24 hours, any free-form text message sent via the API will be **rejected by Meta** with error code 131047.

Currently, `server.py` function `api_broadcast()` (line ~936) calls `send_whatsapp_message()` which sends free-form text. This will fail for most campaign recipients.

The `send_template_message()` function exists at line ~249 in `server.py` but is **never called** by campaigns.

### Implementation

#### 4.1 Update Campaign Creation to Require Template Selection

In `core/outbound.py` → `create_campaign()`:

```python
def create_campaign(
    name: str,
    message: str,
    template_id: str = "",       # <-- NEW: required for campaigns
    template_params: dict = None, # <-- NEW: template variable values
    filter_stage: str = "",
    filter_tag: str = "",
    contact_ids: list = None,
    reply_mode: str = "auto_ai",
    campaign_kb: str = "",
    send_as_template: bool = True,  # <-- NEW: default True
) -> dict:
```

#### 4.2 Update Campaign Execution in `server.py`

In the `api_broadcast()` function (line ~936), add template sending logic:

```python
# Inside the contact loop in api_broadcast():
if campaign.get("template_id") and campaign.get("send_as_template", True):
    template = get_template(campaign["template_id"])
    if not template:
        results["failed"] += 1
        continue

    # Render template with contact-specific variables
    rendered = render_template(
        template["id"],
        contact,
        custom_vars=campaign.get("template_params", {})
    )

    # Send via template API
    result = await send_template_message(
        phone,
        template["name"],
        template.get("language", "en"),
        components=_build_template_components(template, contact)
    )
else:
    # Fallback: free-form text (only works within 24h session window)
    text = personalize_message(message, contact)
    result = await send_whatsapp_message(phone, text)
```

#### 4.3 Add Template Component Builder

```python
def _build_template_components(template: dict, contact: dict) -> list:
    """Build WhatsApp template component parameters from contact data."""
    components = []

    # Body parameters
    body_vars = template.get("variables", [])
    if body_vars:
        params = []
        for var in body_vars:
            value = contact.get(var, var)  # Use contact field or raw value
            params.append({"type": "text", "text": str(value)})
        components.append({"type": "body", "parameters": params})

    # Header (if image/document)
    header = template.get("header", {})
    if header.get("type") == "image" and header.get("url"):
        components.append({
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": header["url"]}}]
        })

    return components
```

#### 4.4 Update Campaign Wizard Frontend (`Campaigns.jsx`)

In Step 2 (Message), add template selector:
- Dropdown to select from approved templates (`api.templates.list()`)
- Show template preview with variables highlighted
- "Use free-form text (24h window only)" toggle with warning icon
- Variable mapping UI: map template variables to contact fields (`name`, `company`, `deal_value`) or custom text

#### 4.5 Acceptance Criteria

- [ ] Campaigns default to template-based sending
- [ ] Template variables are correctly populated per-contact
- [ ] Free-form campaigns show a warning: "Will only be delivered to contacts who messaged in last 24 hours"
- [ ] `send_template_message()` correctly builds the WhatsApp API payload
- [ ] Failed template sends (e.g., template not approved) are captured in campaign stats

---

## 5. P0 — Webhook Security: Mandatory Signature Verification

### The Problem

In `server.py` → `webhook_receive()` (line ~333):

```python
wa_app_secret = os.environ.get("WA_APP_SECRET", "")
if wa_app_secret:
    # verify signature
```

If `WA_APP_SECRET` is not set, **all webhook requests are accepted without verification**. An attacker can POST crafted JSON to `/webhook` and inject fake messages into any conversation.

### Fix

```python
@app.post("/webhook")
async def webhook_receive(request: Request):
    wa_app_secret = os.environ.get("WA_APP_SECRET", "")

    if not wa_app_secret:
        logger.error("WA_APP_SECRET not configured — rejecting all webhooks for security")
        raise HTTPException(status_code=503, detail="Webhook signature verification not configured")

    import hmac as _hmac
    import hashlib as _hashlib

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    raw_body = await request.body()
    expected = "sha256=" + _hmac.new(
        wa_app_secret.encode(), raw_body, _hashlib.sha256
    ).hexdigest()

    if not _hmac.compare_digest(signature_header, expected):
        logger.warning("Webhook signature mismatch — request rejected")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # ... continue processing
```

Changes:
1. **Remove the `if wa_app_secret:` conditional.** If the secret is missing, REJECT the request, don't silently accept it.
2. Add a startup check: if `WA_APP_SECRET` is not set, log a CRITICAL warning.
3. Add onboarding step: "Configure WA_APP_SECRET" in `core/onboarding.py`.

### Acceptance Criteria

- [ ] Webhook rejects all requests when `WA_APP_SECRET` is not set (503 status)
- [ ] Webhook rejects requests with invalid/missing signature (403 status)
- [ ] Valid Meta webhook requests are accepted normally
- [ ] Startup logs a CRITICAL warning if `WA_APP_SECRET` is not configured
- [ ] Onboarding checklist includes this as a required step

---

## 6. P1 — Background Job Queue for Campaign Sends

### The Problem

`api_broadcast()` in `server.py` (line ~936) loops through contacts synchronously:

```python
for contact in targets:
    phone = contact["phone"]
    try:
        result = await send_whatsapp_message(phone, text)
        ...
```

A campaign to 5,000 contacts will take ~25 minutes (assuming 300ms per API call), blocking the HTTP response and the entire server process.

### Implementation

#### 6.1 Add `core/job_queue.py`

Use `asyncio` task queue with persistence. For V1, this is simpler than adding Redis/Celery.

```python
"""
Nazar — Async Job Queue

In-process job queue with persistence and progress tracking.
Jobs survive server restarts via a SQLite jobs table.

For V2: Replace with Celery + Redis for horizontal scaling.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum

logger = logging.getLogger("nazar")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobQueue:
    def __init__(self, max_concurrent: int = 3):
        self.jobs: dict[str, dict] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task] = {}

    async def enqueue(self, job_type: str, params: dict, callback) -> str:
        job_id = str(uuid.uuid4())[:12]
        self.jobs[job_id] = {
            "id": job_id,
            "type": job_type,
            "status": JobStatus.PENDING,
            "params": params,
            "progress": {"current": 0, "total": 0, "failed": 0},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
        task = asyncio.create_task(self._run(job_id, callback, params))
        self._tasks[job_id] = task
        return job_id

    async def _run(self, job_id: str, callback, params: dict):
        async with self.semaphore:
            job = self.jobs[job_id]
            job["status"] = JobStatus.RUNNING
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            try:
                await callback(job_id, params, self._update_progress)
                job["status"] = JobStatus.COMPLETED
            except Exception as e:
                job["status"] = JobStatus.FAILED
                job["error"] = str(e)
                logger.error(f"Job {job_id} failed: {e}")
            finally:
                job["completed_at"] = datetime.now(timezone.utc).isoformat()

    def _update_progress(self, job_id: str, current: int, total: int, failed: int = 0):
        if job_id in self.jobs:
            self.jobs[job_id]["progress"] = {
                "current": current, "total": total, "failed": failed
            }

    def get_job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        if job_id in self._tasks:
            self._tasks[job_id].cancel()
            self.jobs[job_id]["status"] = JobStatus.CANCELLED
            return True
        return False


job_queue = JobQueue(max_concurrent=3)
```

#### 6.2 Refactor `api_broadcast()` to Use Queue

```python
@app.post("/api/campaigns")
async def api_create_campaign(request: Request):
    body = await request.json()
    # ... validation ...

    campaign = create_campaign(...)

    # Enqueue send job (returns immediately)
    job_id = await job_queue.enqueue(
        job_type="campaign_send",
        params={"campaign_id": campaign["id"], "targets": target_ids},
        callback=_execute_campaign_job,
    )

    return {"campaign": campaign, "job_id": job_id, "status": "queued"}


async def _execute_campaign_job(job_id: str, params: dict, update_progress):
    """Background job: send campaign messages one-by-one with rate limiting."""
    campaign_id = params["campaign_id"]
    target_ids = params["targets"]
    campaign = get_campaign(campaign_id)

    total = len(target_ids)
    sent = 0
    failed = 0

    for i, contact_id in enumerate(target_ids):
        contact = get_contact(contact_id)
        if not contact:
            failed += 1
            continue

        # Check opt-out
        if contact.get("opt_out"):
            failed += 1
            continue

        phone = contact["phone"]
        try:
            if campaign.get("template_id"):
                await send_template_message(phone, ...)
            else:
                text = personalize_message(campaign["message"], contact)
                await send_whatsapp_message(phone, text)
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"Campaign send failed for {contact_id}: {e}")

        update_progress(job_id, i + 1, total, failed)

        # Broadcast progress via WebSocket
        await ws_manager.broadcast("default", "campaign:progress", {
            "campaign_id": campaign_id,
            "sent": sent,
            "total": total,
            "failed": failed,
        })

        # Rate limit: 50ms between sends (20/sec — well under WhatsApp limits)
        await asyncio.sleep(0.05)

    # Update campaign record with final stats
    update_campaign(campaign_id, {
        "status": "sent",
        "stats": {"sent": sent, "failed": failed, "total": total},
    })
```

#### 6.3 Add Job Status Endpoint

```python
@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str, request: Request):
    _check_api_key(request)
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
```

#### 6.4 Frontend: Campaign Progress UI

In `Campaigns.jsx`, after creating a campaign:
- Show a progress bar component
- Poll `/api/jobs/{job_id}` every 2 seconds (or use WebSocket `campaign:progress` event)
- Show: "Sending... 1,247 / 5,000 (3 failed)"
- When complete: "Campaign sent! 4,997 delivered, 3 failed"

### Acceptance Criteria

- [ ] Campaign creation returns immediately with `job_id`
- [ ] Campaign sends happen in background at controlled rate
- [ ] Progress is visible in dashboard via WebSocket
- [ ] Failed sends don't block remaining sends
- [ ] Job can be cancelled mid-send
- [ ] Server crash mid-campaign doesn't lose state (persist progress to DB)

---

## 7. P1 — Agent Assignment & Conversation Routing

### The Problem

When `human_only` or `ai_draft` mode triggers, there is no concept of "which agent handles this conversation." All agents see everything. At 5+ agents, conversations are missed or double-handled.

### Implementation

#### 7.1 Database Schema (add to `core/database.py`)

```python
class ConversationAssignment(Base):
    __tablename__ = "conversation_assignments"

    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), primary_key=True)
    assigned_to: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    assigned_by: Mapped[str] = mapped_column(String(36), nullable=True)  # "auto" or user_id
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, resolved, transferred
```

#### 7.2 Create `core/assignment_manager.py`

```python
"""
Nazar — Conversation Assignment Manager

Handles agent routing, assignment, and workload balancing.

Routing strategies:
  round_robin  — Distribute evenly across available agents
  least_busy   — Assign to agent with fewest active conversations
  manual       — No auto-assignment; agents claim from queue
"""

ROUTING_STRATEGIES = ("round_robin", "least_busy", "manual")


def assign_conversation(contact_id: str, agent_id: str = None, strategy: str = "round_robin"):
    """Assign a conversation to an agent."""
    ...

def claim_conversation(contact_id: str, agent_id: str):
    """Agent claims an unassigned conversation from queue."""
    ...

def transfer_conversation(contact_id: str, from_agent: str, to_agent: str, reason: str = ""):
    """Transfer a conversation between agents."""
    ...

def get_agent_conversations(agent_id: str) -> list:
    """Get all conversations assigned to an agent."""
    ...

def get_unassigned_queue() -> list:
    """Get all conversations waiting for assignment."""
    ...

def get_agent_workload() -> dict:
    """Get conversation counts per agent for load balancing."""
    ...
```

#### 7.3 Wire into `_handle_text_message`

When reply mode is `human_only` or `ai_draft`:
1. Check if conversation already assigned
2. If not, auto-assign based on configured strategy
3. Send WebSocket event to assigned agent only (or all if `manual` strategy)

#### 7.4 Frontend: Agent Assignment UI

- In `ConversationDetail.jsx`: Show assigned agent badge, "Transfer" button
- In `Conversations.jsx`: Filter "My Conversations" vs "All" vs "Unassigned"
- In `Handoffs.jsx`: Show assignment queue
- In `Settings.jsx`: Configure routing strategy

### Acceptance Criteria

- [ ] Conversations are auto-assigned on handoff/human_only trigger
- [ ] Agents see "My Conversations" filter
- [ ] Transfer works with audit trail
- [ ] Unassigned conversations are visible in a queue
- [ ] Round-robin distributes evenly (test with 5 agents, 20 conversations)

---

## 8. P1 — Opt-out / Unsubscribe Handling

### Why This Is Critical

WhatsApp Business Policy requires businesses to respect opt-out requests. Failure to do so results in:
- Quality rating downgrade
- Messaging limits reduced
- Phone number ban

### Implementation

#### 8.1 STOP Keyword Detection

Add to `_handle_text_message` in `server.py`, BEFORE any other processing:

```python
STOP_KEYWORDS = {"stop", "unsubscribe", "opt out", "optout", "cancel", "quit", "don't message", "remove me"}

async def _handle_text_message(phone: str, text: str, msg_id: str, msg_type: str = "text"):
    text_lower = text.strip().lower()

    # Check for opt-out FIRST
    if text_lower in STOP_KEYWORDS or text_lower.startswith("stop"):
        await _handle_opt_out(phone, text)
        return

    # ... rest of existing logic
```

#### 8.2 Opt-out Handler

```python
async def _handle_opt_out(phone: str, original_text: str):
    """Handle opt-out request from a contact."""
    contact = get_contact_by_phone(phone)
    if contact:
        # Mark contact as opted out
        update_contact(contact["contact_id"], {"opt_out": True})
        # Remove from all campaign associations
        clear_contact_campaign(contact["contact_id"])

    # Insert into opt_outs table
    # ... DB insert ...

    # Send confirmation (WhatsApp requires this)
    await send_whatsapp_message(phone,
        "You've been unsubscribed from messages. "
        "Reply START to opt back in anytime."
    )

    log_event("contact.opted_out", {
        "phone": phone,
        "contact_id": contact["contact_id"] if contact else None,
        "original_text": original_text,
    })
```

#### 8.3 Opt-in Re-subscribe

```python
START_KEYWORDS = {"start", "subscribe", "opt in", "optin", "resume"}

# In _handle_text_message, check start keywords:
if text_lower in START_KEYWORDS:
    await _handle_opt_in(phone, text)
    return
```

#### 8.4 Campaign Send Guard

In the campaign send loop (and in `execute_broadcast`):

```python
# Before sending to each contact:
if contact.get("opt_out"):
    results["skipped"] += 1
    continue
```

#### 8.5 Frontend: Opt-out Management

- In `Contacts.jsx`: Show opt-out badge, filter by opted-out contacts
- In `Settings.jsx`: Configure opt-out keywords, auto-response message
- In campaign stats: Show "skipped (opted out)" count

### Acceptance Criteria

- [ ] "STOP" message immediately opts out the contact
- [ ] Opted-out contacts are excluded from ALL future campaigns
- [ ] Opt-out confirmation is sent automatically
- [ ] "START" message re-subscribes the contact
- [ ] Opt-out status is visible in contact profile
- [ ] Campaign stats show skipped count

---

## 9. P1 — Campaign Scheduling & Drip Campaigns

### Implementation

#### 9.1 Add Schedule Fields to Campaign Model

In `core/database.py` → `Campaign` table (already included in section 2):
- `scheduled_at: DateTime` — when to send
- `status: String` — `draft`, `scheduled`, `sending`, `sent`, `failed`

In `core/outbound.py` → `create_campaign()`:
```python
def create_campaign(
    ...,
    scheduled_at: str = None,  # ISO datetime string
    drip_config: dict = None,  # {"delay_days": 3, "followup_message": "..."}
):
```

#### 9.2 Campaign Scheduler Loop

Add to `server.py` startup (alongside existing `_auto_resume_loop`):

```python
async def _campaign_scheduler_loop():
    """Check for scheduled campaigns and execute them when due."""
    while True:
        try:
            now = datetime.now(IST)
            campaigns = get_campaign_history()
            for campaign in campaigns:
                if campaign.get("status") != "scheduled":
                    continue
                scheduled = datetime.fromisoformat(campaign["scheduled_at"])
                if scheduled <= now:
                    logger.info(f"Executing scheduled campaign: {campaign['id']}")
                    update_campaign(campaign["id"], {"status": "sending"})
                    await job_queue.enqueue(
                        "campaign_send",
                        {"campaign_id": campaign["id"]},
                        _execute_campaign_job,
                    )
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        await asyncio.sleep(30)  # Check every 30 seconds
```

#### 9.3 Drip Campaign Engine

```python
async def _drip_campaign_loop():
    """Check for drip campaign follow-ups that are due."""
    while True:
        try:
            # Query campaign_contacts where:
            # - campaign has drip_config
            # - contact has been sent the initial message
            # - delay_days have passed since initial send
            # - followup has not been sent yet
            # Send followup_message to qualifying contacts
            ...
        except Exception as e:
            logger.error(f"Drip engine error: {e}")
        await asyncio.sleep(60)
```

#### 9.4 Frontend: Schedule UI

In `Campaigns.jsx` → Step 2 or Step 4:
- "Send now" / "Schedule for later" toggle
- Date/time picker (with timezone display)
- Drip followup config: "Send follow-up after X days to non-responders"

### Acceptance Criteria

- [ ] Campaign can be scheduled for a future date/time
- [ ] Scheduled campaigns show as "Scheduled" in campaign list with countdown
- [ ] Scheduled campaigns execute within 1 minute of their scheduled time
- [ ] Drip follow-ups are sent to non-responders after configured delay
- [ ] Scheduled campaigns can be cancelled before execution
- [ ] Timezone handling is correct (IST)

---

## 10. P1 — WhatsApp API Rate Limiting

### The Problem

WhatsApp Business API has rate limits:
- Tier 1: 1,000 business-initiated conversations / 24h
- Tier 2: 10,000 / 24h
- Tier 3: 100,000 / 24h
- Per-second: ~80 messages/second max

Currently, campaign sends fire as fast as Python can loop. Meta will throttle, rate-limit, or ban the number.

### Implementation

#### 10.1 Add Rate Limiter to `send_whatsapp_message` and `send_template_message`

```python
import asyncio
from collections import deque
import time

class WhatsAppRateLimiter:
    """
    Sliding window rate limiter for WhatsApp API calls.
    Respects both per-second and daily limits.
    """

    def __init__(self, max_per_second: int = 20, max_per_day: int = 1000):
        self.max_per_second = max_per_second
        self.max_per_day = max_per_day
        self._second_window: deque = deque()
        self._day_count: int = 0
        self._day_reset: float = time.time() + 86400
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a send slot is available."""
        async with self._lock:
            now = time.time()

            # Reset daily counter
            if now > self._day_reset:
                self._day_count = 0
                self._day_reset = now + 86400

            # Check daily limit
            if self._day_count >= self.max_per_day:
                raise Exception(f"WhatsApp daily limit reached ({self.max_per_day})")

            # Enforce per-second limit
            while len(self._second_window) >= self.max_per_second:
                oldest = self._second_window[0]
                wait_time = 1.0 - (now - oldest)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.time()
                self._second_window.popleft()

            self._second_window.append(now)
            self._day_count += 1


wa_rate_limiter = WhatsAppRateLimiter(max_per_second=20, max_per_day=1000)

# Wrap existing send functions:
async def send_whatsapp_message(phone: str, text: str) -> dict:
    await wa_rate_limiter.acquire()
    # ... existing send logic ...
```

#### 10.2 Configure Tier via Settings

In `Settings.jsx` → WhatsApp Configuration section:
- Dropdown: "WhatsApp Tier" → Tier 1 (1K/day), Tier 2 (10K/day), Tier 3 (100K/day)
- This updates `config.json` → `whatsapp_tier`
- Rate limiter reads this on init

### Acceptance Criteria

- [ ] Campaign sends are rate-limited to 20/sec
- [ ] Daily limit is enforced (campaign stops, not crashes, when reached)
- [ ] Rate limit is configurable via settings
- [ ] Campaign shows "paused — daily limit reached" status when throttled

---

## 11. P2 — Media Message Support (Inbound + Outbound)

### Current State

In `_handle_text_message` (line ~415), voice messages are transcribed via `_handle_voice_message`, but images, documents, and videos are completely ignored:

```python
if msg_type == "audio":
    t1 = asyncio.create_task(_handle_voice_message(phone, media_id, msg_id))
    t2 = asyncio.create_task(mark_as_read(msg_id))
```

Image/document/video messages fall through to the `else` clause and get treated as text with content like `"[Image message]"`.

### Implementation

#### 11.1 Inbound Media Handling

```python
async def _handle_media_message(phone: str, media_id: str, media_type: str, msg_id: str, caption: str = ""):
    """
    Handle inbound image/document/video messages.
    1. Download from WhatsApp CDN
    2. Store locally (encrypted)
    3. Save message with media reference
    4. If image: describe via vision LLM for AI context
    """
    # Download media
    media_bytes, mime_type = await download_whatsapp_media(media_id)
    if not media_bytes:
        logger.error(f"Failed to download media {media_id}")
        return

    # Store media file (encrypted)
    contact = get_contact_by_phone(phone)
    if not contact:
        return

    media_dir = DATA_DIR / "media" / contact["contact_id"]
    media_dir.mkdir(parents=True, exist_ok=True)
    ext = _mime_to_extension(mime_type)
    filename = f"{msg_id}.{ext}"
    media_path = media_dir / filename
    # Encrypt and save
    from encryption import encrypt_data
    encrypted = encrypt_data(phone, media_bytes)
    media_path.write_bytes(encrypted)

    # Save message record
    text_content = caption or f"[{media_type.title()} message]"
    save_message(contact["contact_id"], "inbound", text_content, msg_id=msg_id,
                 content_type=media_type, media_path=str(media_path))

    # For images: use vision LLM to describe for AI context
    if media_type == "image" and caption == "":
        # Optional: call Claude vision API to understand the image
        pass
```

#### 11.2 Outbound Media Sending

Add to `server.py`:

```python
async def send_whatsapp_media(phone: str, media_type: str, media_url: str, caption: str = "") -> dict:
    """Send an image/document/video via WhatsApp."""
    await wa_rate_limiter.acquire()
    headers = { ... }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": media_type,
        media_type: {
            "link": media_url,
            **({"caption": caption} if caption else {}),
        }
    }
    # ... send via aiohttp ...
```

#### 11.3 Frontend: Media Display

In `ConversationDetail.jsx`:
- Render image messages as inline thumbnails (click to expand)
- Render document messages as download links with file icon
- Render voice notes with audio player
- Add "Attach" button to message compose area for outbound media

#### 11.4 Add `save_message` Signature Update

In `contact_manager.py`, update `save_message()`:
```python
def save_message(contact_id, direction, text, msg_id=None,
                 content_type="text", media_path=None):
```

### Acceptance Criteria

- [ ] Inbound images display as thumbnails in conversation
- [ ] Inbound documents show as downloadable files
- [ ] Inbound voice notes show with audio player + transcription
- [ ] Outbound media can be sent from conversation UI
- [ ] Media files are encrypted at rest
- [ ] AI context includes image descriptions (when vision is available)

---

## 12. P2 — Contact Segmentation Engine

### Current State

Campaign targeting in `api_broadcast()` supports:
- Filter by single pipeline stage (`filter_stage`)
- Filter by single tag (`filter_tag`)
- Explicit contact IDs (`contact_ids`)

This is far too limited for real campaigns.

### Implementation

#### 12.1 Create `core/segmentation.py`

```python
"""
Nazar — Contact Segmentation Engine

Build complex audience segments with AND/OR conditions for campaign targeting.

Segment definition format:
{
    "conditions": [
        {"field": "stage", "operator": "in", "value": ["Qualified", "Proposal"]},
        {"field": "lead_score", "operator": "gte", "value": 60},
        {"field": "tags", "operator": "contains", "value": "enterprise"},
        {"field": "last_contact_days", "operator": "gte", "value": 7},
        {"field": "opt_out", "operator": "eq", "value": false},
    ],
    "logic": "AND"  # AND = all must match, OR = any must match
}
"""

OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in a if isinstance(a, (list, str)) else False,
    "not_contains": lambda a, b: b not in a if isinstance(a, (list, str)) else True,
    "starts_with": lambda a, b: str(a).startswith(str(b)),
    "exists": lambda a, b: a is not None and a != "",
    "not_exists": lambda a, b: a is None or a == "",
}

SEGMENTABLE_FIELDS = {
    "stage": "Pipeline Stage",
    "lead_score": "Lead Score",
    "tags": "Tags",
    "source": "Lead Source",
    "company": "Company",
    "deal_value": "Deal Value",
    "last_contact_days": "Days Since Last Contact",
    "opt_out": "Opted Out",
    "created_days_ago": "Days Since Created",
    "reply_mode": "Reply Mode",
}


def evaluate_segment(contacts: list, segment: dict) -> list:
    """Filter contacts matching segment conditions."""
    conditions = segment.get("conditions", [])
    logic = segment.get("logic", "AND")

    if not conditions:
        return contacts

    results = []
    for contact in contacts:
        matches = [_evaluate_condition(contact, cond) for cond in conditions]
        if logic == "AND" and all(matches):
            results.append(contact)
        elif logic == "OR" and any(matches):
            results.append(contact)

    return results


def _evaluate_condition(contact: dict, condition: dict) -> bool:
    """Evaluate a single condition against a contact."""
    field = condition["field"]
    operator = condition["operator"]
    value = condition["value"]

    # Computed fields
    if field == "last_contact_days":
        actual = _days_since(contact.get("last_contact_at"))
    elif field == "created_days_ago":
        actual = _days_since(contact.get("created_at"))
    else:
        actual = contact.get(field)

    op_func = OPERATORS.get(operator)
    if not op_func:
        return False

    try:
        return op_func(actual, value)
    except (TypeError, ValueError):
        return False
```

#### 12.2 Saved Segments

Allow saving segment definitions for reuse:

```python
def save_segment(name: str, segment: dict) -> dict:
    """Save a named segment for reuse in campaigns."""
    ...

def list_segments() -> list:
    """List all saved segments."""
    ...

def get_segment_preview(segment: dict) -> dict:
    """Return count and sample contacts matching a segment."""
    ...
```

#### 12.3 Frontend: Segment Builder UI

In `Campaigns.jsx` → Step 1 (Audience):
- Visual segment builder with condition rows
- Each row: Field dropdown → Operator dropdown → Value input
- AND/OR toggle
- "Preview Audience" button showing count + sample contacts
- "Save Segment" to reuse later
- "Load Saved Segment" dropdown

### Acceptance Criteria

- [ ] Segments with multiple AND conditions correctly filter contacts
- [ ] OR logic works for any-match scenarios
- [ ] All SEGMENTABLE_FIELDS are supported
- [ ] Saved segments persist and can be loaded
- [ ] Audience preview shows count and 5 sample contacts
- [ ] Opted-out contacts are always excluded regardless of segment

---

## 13. P2 — Structured Knowledge Base with RAG

### Current State

`data/knowledge_base.txt` is a single flat file. `_load_knowledge_base()` in `conversation.py` reads the entire file and injects it into the system prompt. This:
- Doesn't scale past ~4K tokens of KB content
- Has no structure (FAQs vs product specs vs pricing)
- Can't handle PDF/CSV uploads
- Doesn't use semantic search (relevant chunks only)

Campaign KB (`campaign_kb/*.txt`) has the same problem.

### Implementation

#### 13.1 Create `core/knowledge_base.py`

```python
"""
Nazar — Structured Knowledge Base with RAG

Supports:
- Multiple KB documents (text, PDF extract, CSV)
- Document chunking (512 tokens per chunk)
- ChromaDB vector storage for semantic search
- Query-time retrieval: only inject relevant chunks into prompt
- Campaign-scoped KB (separate collection per campaign)
"""

import uuid
import logging
from pathlib import Path
from typing import Optional

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = False

logger = logging.getLogger("nazar")


class KnowledgeBaseManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.kb_dir = data_dir / "knowledge_base"
        self.kb_dir.mkdir(parents=True, exist_ok=True)

        if CHROMADB_AVAILABLE:
            self.client = chromadb.PersistentClient(
                path=str(self.kb_dir / "vectors")
            )
        else:
            self.client = None

    def add_document(self, title: str, content: str, doc_type: str = "text",
                     scope: str = "global", campaign_id: str = None) -> dict:
        """
        Add a document to the knowledge base.
        Content is automatically chunked and embedded.
        """
        doc_id = str(uuid.uuid4())[:12]
        chunks = self._chunk_text(content, chunk_size=512)

        collection_name = f"kb_{scope}" if scope == "global" else f"kb_campaign_{campaign_id}"

        if self.client:
            collection = self.client.get_or_create_collection(collection_name)
            collection.add(
                ids=[f"{doc_id}_chunk_{i}" for i in range(len(chunks))],
                documents=chunks,
                metadatas=[{"doc_id": doc_id, "title": title, "chunk_index": i}
                           for i in range(len(chunks))],
            )

        # Save raw document
        doc_meta = {
            "id": doc_id,
            "title": title,
            "type": doc_type,
            "scope": scope,
            "campaign_id": campaign_id,
            "chunk_count": len(chunks),
            "char_count": len(content),
        }
        # Save to docs index
        return doc_meta

    def query(self, question: str, scope: str = "global",
              campaign_id: str = None, n_results: int = 5) -> str:
        """
        Retrieve relevant KB chunks for a question.
        Returns concatenated relevant text for injection into system prompt.
        """
        if not self.client:
            return self._fallback_full_text(scope, campaign_id)

        collection_name = f"kb_{scope}" if scope == "global" else f"kb_campaign_{campaign_id}"

        try:
            collection = self.client.get_collection(collection_name)
            results = collection.query(query_texts=[question], n_results=n_results)
            if results and results["documents"]:
                return "\n\n---\n\n".join(results["documents"][0])
        except Exception as e:
            logger.warning(f"KB query failed: {e}")

        return self._fallback_full_text(scope, campaign_id)

    def _chunk_text(self, text: str, chunk_size: int = 512) -> list:
        """Split text into overlapping chunks."""
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - 50):  # 50-word overlap
            chunk = " ".join(words[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks or [text]

    def _fallback_full_text(self, scope, campaign_id) -> str:
        """Fallback: return full text if ChromaDB is unavailable."""
        if scope == "global":
            path = self.data_dir / "knowledge_base.txt"
        else:
            path = self.data_dir / "campaign_kb" / f"{campaign_id}.txt"
        if path.exists():
            return path.read_text()[:4000]
        return ""

    def list_documents(self, scope: str = "global", campaign_id: str = None) -> list:
        """List all documents in a KB scope."""
        ...

    def delete_document(self, doc_id: str):
        """Delete a document and its chunks."""
        ...
```

#### 13.2 Update `_build_system_prompt` in `conversation.py`

Replace:
```python
knowledge_base = _load_knowledge_base()
```

With:
```python
# Retrieve only relevant KB chunks based on the customer's latest message
kb_manager = KnowledgeBaseManager(DATA_DIR.parent)
relevant_kb = kb_manager.query(
    question=latest_customer_message,
    scope="global",
)
if campaign_kb:
    campaign_relevant = kb_manager.query(
        question=latest_customer_message,
        scope="campaign",
        campaign_id=campaign_id,
    )
    relevant_kb = f"{relevant_kb}\n\n--- Campaign-specific ---\n\n{campaign_relevant}"
```

#### 13.3 Frontend: KB Management Page (`KnowledgeBase.jsx`)

Currently `KnowledgeBase.jsx` is a single textarea. Replace with:
- Document list with title, type, chunk count
- "Add Document" → text input, or file upload (PDF, TXT, CSV)
- PDF upload: extract text server-side using `pypdf2` or `pdfplumber`
- Each document can be edited/deleted
- "Test Query" input: type a question, see which chunks are returned
- Campaign KB tab: manage per-campaign documents

#### 13.4 Add to `requirements.txt`

```
pdfplumber>=0.10.0
```

### Acceptance Criteria

- [ ] Documents are chunked and stored in ChromaDB collections
- [ ] Query returns only relevant chunks (not entire KB)
- [ ] PDF upload extracts text and indexes it
- [ ] Campaign-scoped KB is separate from global KB
- [ ] AI responses use relevant chunks instead of full KB dump
- [ ] KB management UI allows CRUD on documents

---

## 14. P2 — Outbound Webhooks & CRM Integrations

### Implementation

#### 14.1 Create `core/webhook_dispatcher.py`

```python
"""
Nazar — Outbound Webhook Dispatcher

Send events to external systems (Zapier, CRM, Slack, custom URLs).

Configurable webhooks:
- message.inbound — when a customer messages
- message.outbound — when a reply is sent
- contact.created — new contact added
- contact.stage_changed — pipeline movement
- handoff.triggered — AI → human handoff
- campaign.completed — campaign finished
- draft.pending — AI draft awaiting approval
"""

import aiohttp
import asyncio
import hmac
import hashlib
import json
import logging
from datetime import datetime

logger = logging.getLogger("nazar")


SUPPORTED_EVENTS = [
    "message.inbound",
    "message.outbound",
    "contact.created",
    "contact.stage_changed",
    "contact.opted_out",
    "handoff.triggered",
    "handoff.resolved",
    "campaign.completed",
    "draft.pending",
    "draft.approved",
]


class WebhookDispatcher:
    def __init__(self):
        self.webhooks: list[dict] = []  # Load from config/DB

    async def dispatch(self, event_type: str, payload: dict):
        """Send event to all subscribed webhook endpoints."""
        for webhook in self.webhooks:
            if event_type in webhook.get("events", []) or "*" in webhook.get("events", []):
                asyncio.create_task(self._send(webhook, event_type, payload))

    async def _send(self, webhook: dict, event_type: str, payload: dict):
        body = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": payload,
        }
        body_str = json.dumps(body)

        headers = {"Content-Type": "application/json"}

        # HMAC signature for verification
        if webhook.get("secret"):
            sig = hmac.new(
                webhook["secret"].encode(),
                body_str.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Nazar-Signature"] = f"sha256={sig}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook["url"],
                    data=body_str,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(f"Webhook {webhook['url']} returned {resp.status}")
        except Exception as e:
            logger.error(f"Webhook dispatch failed: {e}")
```

#### 14.2 API Endpoints

```
POST   /api/webhooks          — Register a new webhook
GET    /api/webhooks          — List all webhooks
DELETE /api/webhooks/{id}     — Remove a webhook
POST   /api/webhooks/{id}/test — Send test event
```

#### 14.3 Frontend: Webhooks Settings Page

In `Settings.jsx`, add "Integrations" tab:
- Webhook URL input
- Event checkboxes (select which events to receive)
- Secret key input (for HMAC verification)
- "Test" button → sends sample event
- List of configured webhooks

### Acceptance Criteria

- [ ] Webhooks fire within 1 second of the triggering event
- [ ] HMAC signatures are correct and verifiable
- [ ] Failed webhooks don't block the main flow
- [ ] Test webhook sends a sample payload
- [ ] Webhook logs show delivery status

---

## 15. P2 — Campaign Analytics Enhancement

### Current State

`core/analytics.py` → `get_campaign_analytics()` only has: total sent, failed, targeted, delivery rate. No per-campaign reply rates, no conversion tracking, no A/B testing.

### Implementation

#### 15.1 Per-Campaign Reply Tracking

When an inbound message arrives and the contact has a campaign association:
```python
# In _handle_text_message, after saving the message:
campaign_id = get_contact_campaign(contact_id)
if campaign_id:
    # Update campaign_contacts record: status = "replied"
    # Increment campaign reply count
    update_campaign_contact_status(campaign_id, contact_id, "replied")
```

#### 15.2 Conversion Tracking

Track when a contact moves pipeline stages after receiving a campaign:
```python
# In move_stage() or when contact.stage changes:
campaign_id = get_contact_campaign(contact_id)
if campaign_id:
    log_event("campaign.conversion", {
        "campaign_id": campaign_id,
        "contact_id": contact_id,
        "from_stage": old_stage,
        "to_stage": new_stage,
    })
```

#### 15.3 Campaign Analytics Endpoint Enhancement

```python
@app.get("/api/campaigns/{campaign_id}/analytics")
async def api_campaign_analytics(campaign_id: str, request: Request):
    _check_api_key(request)
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Per-recipient status breakdown
    recipients = get_campaign_contacts(campaign_id)

    return {
        "campaign": campaign,
        "delivery": {
            "sent": sum(1 for r in recipients if r["status"] in ("sent", "delivered", "read", "replied")),
            "delivered": sum(1 for r in recipients if r["status"] in ("delivered", "read", "replied")),
            "read": sum(1 for r in recipients if r["status"] in ("read", "replied")),
            "replied": sum(1 for r in recipients if r["status"] == "replied"),
            "failed": sum(1 for r in recipients if r["status"] == "failed"),
        },
        "rates": {
            "delivery_rate": ...,
            "open_rate": ...,
            "reply_rate": ...,
        },
        "conversions": {
            "stage_advances": ...,  # Contacts who moved forward in pipeline
            "pipeline_value_generated": ...,
        },
        "time_to_reply": {
            "median_minutes": ...,
            "p90_minutes": ...,
        },
    }
```

#### 15.4 A/B Testing (Future — add schema now)

```python
class ABTest(Base):
    __tablename__ = "ab_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"))
    campaign_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"))
    split_ratio: Mapped[float] = mapped_column(Float, default=0.5)
    winner_metric: Mapped[str] = mapped_column(String(50), default="reply_rate")
    status: Mapped[str] = mapped_column(String(20), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

### Acceptance Criteria

- [ ] Per-campaign reply rate is tracked and displayed
- [ ] Conversion tracking shows pipeline movement after campaign
- [ ] Campaign detail page shows full funnel: sent → delivered → read → replied → converted
- [ ] Time-to-reply distribution is calculated

---

## 16. P3 — API Input Validation with Pydantic

### The Problem

Every endpoint does `body = await request.json()` then `body.get("field", "")` with zero validation. Invalid data goes straight to storage.

### Implementation

Add Pydantic models for every endpoint. Example:

```python
from pydantic import BaseModel, Field, validator
from typing import Optional, List


class CreateContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., pattern=r"^\+?[1-9]\d{6,14}$")
    company: str = Field("", max_length=200)
    source: str = Field("manual", max_length=100)
    tags: List[str] = Field(default_factory=list)
    notes: str = Field("", max_length=5000)
    deal_value: float = Field(0.0, ge=0)


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=4096)
    template_id: Optional[str] = None
    filter_stage: Optional[str] = None
    filter_tag: Optional[str] = None
    contact_ids: Optional[List[str]] = None
    reply_mode: str = Field("auto_ai", pattern="^(auto_ai|human_only|ai_draft)$")
    campaign_kb: str = Field("", max_length=10000)
    scheduled_at: Optional[str] = None
    send_as_template: bool = True

    @validator("filter_stage")
    def validate_stage(cls, v):
        if v and v not in PIPELINE_STAGES:
            raise ValueError(f"Invalid stage: {v}")
        return v


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)


class SetReplyModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(auto_ai|human_only|ai_draft)$")


class ApproveDraftRequest(BaseModel):
    edited_text: str = Field("", max_length=4096)


class WebhookConfigRequest(BaseModel):
    url: str = Field(..., pattern=r"^https?://")
    events: List[str] = Field(default_factory=lambda: ["*"])
    secret: Optional[str] = Field(None, max_length=256)


# Usage in endpoints:
@app.post("/api/contacts")
async def api_create_contact(request: Request):
    body = CreateContactRequest(**(await request.json()))
    # Now body.name, body.phone etc. are validated
```

### Scope

Create Pydantic models for ALL 40+ POST/PATCH endpoints in `server.py`. Store models in `core/schemas.py`.

### Acceptance Criteria

- [ ] Every POST/PATCH endpoint uses a Pydantic model
- [ ] Invalid phone numbers return 422 with clear error
- [ ] Over-length strings return 422
- [ ] Invalid enum values (stages, reply modes) return 422
- [ ] All error responses include the field name and constraint violated

---

## 17. P3 — Pagination Across All List Endpoints

### The Problem

These endpoints return ALL records with no limits:
- `GET /api/contacts` → `list_contacts()` — loads every contact profile
- `GET /api/conversations` → all contacts with messages
- `GET /api/campaigns` → `get_campaign_history()` — all campaigns
- `GET /api/broadcasts/history` → `get_broadcast_history()` — all broadcasts
- `GET /api/handoffs/history` → all handoff events
- `GET /api/drafts` → `get_all_pending_drafts()` — all drafts

### Implementation

Add cursor-based pagination (better than offset for real-time data):

```python
@app.get("/api/contacts")
async def api_list_contacts(request: Request):
    _check_api_key(request)
    params = request.query_params
    page = int(params.get("page", 1))
    page_size = min(int(params.get("page_size", 50)), 200)  # Max 200
    stage = params.get("stage")
    tag = params.get("tag")
    search = params.get("search")
    sort_by = params.get("sort_by", "updated_at")  # name, score, updated_at
    sort_order = params.get("sort_order", "desc")

    # With SQLite (section 2), this becomes:
    # SELECT * FROM contacts WHERE ... ORDER BY ... LIMIT ? OFFSET ?
    contacts, total = list_contacts_paginated(
        page=page,
        page_size=page_size,
        stage=stage,
        tag=tag,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return {
        "contacts": contacts,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        }
    }
```

Apply to ALL list endpoints.

### Frontend

Update `useApi` hook and all list pages to support:
- Page number navigation
- Page size selector (25, 50, 100)
- "Load more" for infinite scroll (conversations page)

### Acceptance Criteria

- [ ] No endpoint returns more than 200 records per call
- [ ] Pagination metadata is included in all list responses
- [ ] Frontend shows page navigation
- [ ] 10K contacts page loads in < 500ms

---

## 18. P3 — Session Token Revocation

### The Problem

`auth_manager.py` → `login()` issues HMAC-signed tokens with TTL (line ~407). `validate_token()` checks the HMAC signature and TTL but has **no revocation list**. The `logout()` API is a client-side no-op — the token remains valid until it naturally expires.

### Fix

Add a revocation set (in-memory + persisted):

```python
# In auth_manager.py:

_revoked_tokens: set = set()
_revoked_path = DATA_DIR / "revoked_tokens.json"


def revoke_token(token: str):
    """Add token to revocation list."""
    _revoked_tokens.add(token)
    _persist_revoked()


def _persist_revoked():
    """Persist revoked tokens (prune expired ones)."""
    # Only keep tokens that haven't expired yet
    valid_revoked = set()
    for t in _revoked_tokens:
        try:
            payload = _verify_token_format(t)
            if payload:  # Still within TTL
                valid_revoked.add(t)
        except Exception:
            pass
    _revoked_path.write_text(json.dumps(list(valid_revoked)))


def validate_token(token: str) -> dict:
    # Existing validation...

    # ADD: Check revocation
    if token in _revoked_tokens:
        raise ValueError("Token has been revoked")

    # ... rest of validation
```

Update `api_logout()` in `server.py`:
```python
@app.post("/api/auth/logout")
async def api_logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        revoke_token(token)
    return {"ok": True}
```

### Acceptance Criteria

- [ ] `POST /api/auth/logout` invalidates the token server-side
- [ ] Subsequent requests with revoked token return 401
- [ ] Revocation list survives server restart
- [ ] Expired tokens are auto-pruned from revocation list

---

## 19. P3 — Audit Log System

### Implementation

Use the `AuditLog` table from section 2. Create `core/audit.py`:

```python
"""
Nazar — Audit Logger

Tracks all state-changing actions for compliance, debugging, and accountability.
Every mutation goes through here.
"""

async def log_audit(actor_id: str, action: str, resource_type: str,
                    resource_id: str = None, details: dict = None):
    """
    Log an auditable action.

    Examples:
        log_audit("user_123", "contact.updated", "contact", "c_456", {"stage": "Won"})
        log_audit("user_123", "draft.approved", "draft", "c_789", {"edited": True})
        log_audit("system", "campaign.sent", "campaign", "camp_001", {"sent": 500})
    """
    # Insert into audit_log table
    ...
```

Add `log_audit()` calls to:
- Contact create/update/delete
- Pipeline stage changes
- Reply mode changes
- Draft approve/reject/edit
- Campaign create/send
- Handoff trigger/resume
- Config changes
- User create/delete
- Login/logout

### Frontend: Audit Log Page

Add `/audit` route (admin-only):
- Filterable table: action type, actor, resource, date range
- Each row links to the affected resource

### Acceptance Criteria

- [ ] Every state-changing API call creates an audit log entry
- [ ] Audit log includes actor (who), action (what), resource (on what), timestamp
- [ ] Admin can view audit log in dashboard
- [ ] Audit log is filterable by action type and date range
- [ ] GDPR: audit log itself doesn't contain PII (use contact_id, not name/phone)

---

## 20. P3 — Memory Decay & Archival

### The Problem

ChromaDB stores every message/signal forever with equal weight. A 2-year-old objection carries the same relevance as yesterday's buying signal.

### Implementation

In `core/customer_memory.py`, add:

```python
def prune_stale_memories(contact_id: str, max_age_days: int = 180):
    """
    Remove vector entries older than max_age_days.
    Keeps a summary of pruned content as a single "historical context" entry.
    """
    collection = _get_collection(contact_id)
    if not collection:
        return

    cutoff = (datetime.now(IST) - timedelta(days=max_age_days)).isoformat()
    results = collection.get(where={"timestamp": {"$lt": cutoff}})

    if results and results["ids"]:
        # Generate a summary of old content before deleting
        old_texts = results["documents"]
        summary = _summarize_old_memories(old_texts)  # LLM call

        # Delete old entries
        collection.delete(ids=results["ids"])

        # Add summary as single entry
        collection.add(
            ids=[f"historical_summary_{contact_id}"],
            documents=[summary],
            metadatas=[{"type": "historical_summary", "timestamp": datetime.now(IST).isoformat()}],
        )


def get_relevant_context(contact_id: str, query: str, n_results: int = 5) -> str:
    """
    Updated: Weight recent memories higher.
    """
    # Existing ChromaDB query
    results = collection.query(query_texts=[query], n_results=n_results * 2)

    # Re-rank by recency
    scored = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        age_days = _days_since(meta.get("timestamp"))
        recency_boost = max(0.5, 1.0 - (age_days / 365))  # Linear decay over 1 year
        scored.append((doc, recency_boost))

    scored.sort(key=lambda x: x[1], reverse=True)
    return "\n".join([s[0] for s in scored[:n_results]])
```

Add a nightly background loop:
```python
async def _memory_maintenance_loop():
    """Nightly: prune old memories for all contacts."""
    while True:
        await asyncio.sleep(86400)  # Run daily
        contacts = list_contacts()
        for c in contacts:
            try:
                prune_stale_memories(c["contact_id"])
            except Exception as e:
                logger.error(f"Memory pruning failed for {c['contact_id']}: {e}")
```

### Acceptance Criteria

- [ ] Memories older than 180 days are summarized and pruned
- [ ] Recent memories are weighted higher in retrieval
- [ ] Historical summary captures key facts from old memories
- [ ] Memory pruning runs nightly without affecting active conversations

---

## 21. P3 — Docker & Deployment Configuration

### Create `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Build frontend
WORKDIR /app/dashboard
RUN npm ci && npm run build
WORKDIR /app

# Create data dir
RUN mkdir -p /app/data

EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
```

### Create `docker-compose.yml`

```yaml
version: '3.8'

services:
  nazar:
    build: .
    ports:
      - "8001:8001"
    volumes:
      - nazar_data:/app/data
      - ./.env:/app/.env
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  nazar_data:
    driver: local
```

### Create `.env.example` (rename from `.env.template`)

```bash
# Required
WA_APP_SECRET=your_whatsapp_app_secret
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_ACCESS_TOKEN=your_access_token
WHATSAPP_VERIFY_TOKEN=your_verify_token

# LLM Providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-v1-...
GOOGLE_API_KEY=AIza...

# Optional
GROQ_API_KEY=gsk_...
NAZAR_API_KEY=your_api_key
```

### Acceptance Criteria

- [ ] `docker build .` succeeds
- [ ] `docker-compose up` starts the application
- [ ] Data persists across container restarts
- [ ] Health check works
- [ ] `.env` is properly loaded

---

## 22. P3 — Frontend Error Boundaries & Testing

### 22.1 Error Boundary Component

Create `dashboard/src/components/ErrorBoundary.jsx`:

```jsx
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('Error boundary caught:', error, info);
    // TODO: Send to error tracking service
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <h2>Something went wrong</h2>
          <p>{this.state.error?.message}</p>
          <button onClick={() => this.setState({ hasError: false })}>
            Try Again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Wrap the main app layout and each page route with `<ErrorBoundary>`.

### 22.2 Frontend Testing Setup

```bash
npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
```

Add to `vite.config.js`:
```javascript
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './src/test-setup.js',
}
```

Write tests for:
- `api/client.js` — mock fetch, test error handling
- Key components: Sidebar navigation, ConversationDetail message rendering
- Campaign wizard step navigation
- Auth flow (login, logout, token refresh)

### Acceptance Criteria

- [ ] Error boundary catches and displays JS errors gracefully
- [ ] At least 10 frontend test cases pass
- [ ] `npm test` runs successfully in CI

---

## 23. P3 — Branding Cleanup & i18n Prep

### The Problem

- `core/transcription.py` line 18: `logger = logging.getLogger("innervoice")` — should be `"nazar"`
- `core/transcription.py` docstring says "InnerVoice — Audio Transcription"
- `core/encryption.py` docstring says "InnerVoice — Per-User Encryption Layer"
- `core/customer_memory.py` docstring says "Adapted from InnerVoice's vector_memory.py"

### Fix

Global search-and-replace:
- `"innervoice"` → `"nazar"` in all logger names
- `"InnerVoice"` → `"Nazar"` in all docstrings and comments

### i18n Prep

For future Hindi/regional language support:
1. Extract all UI strings in React components to a `locales/en.json` file
2. Create a `useTranslation()` hook that reads from the locale file
3. Don't implement other languages yet — just make the architecture ready

### Acceptance Criteria

- [ ] No references to "InnerVoice" anywhere in the codebase
- [ ] All loggers use `"nazar"` name
- [ ] Frontend strings are extracted to locale file (English only for now)

---

## 24. P3 — Health Check Enhancements

### Current State

`/health` in `server.py` (line ~1622) returns:
```json
{"status": "ok", "service": "nazar", "timestamp": "..."}
```

It doesn't check anything.

### Enhanced Health Check

```python
@app.get("/health")
async def health():
    checks = {}

    # 1. Data directory writable
    try:
        test_file = DATA_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["storage"] = "ok"
    except Exception as e:
        checks["storage"] = f"error: {e}"

    # 2. ChromaDB connection
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(DATA_DIR / "contacts" / "chroma"))
        client.heartbeat()
        checks["vector_db"] = "ok"
    except Exception as e:
        checks["vector_db"] = f"error: {e}"

    # 3. LLM provider reachability
    try:
        provider_status = llm_health()
        checks["llm"] = provider_status
    except Exception:
        checks["llm"] = "unknown"

    # 4. Database (after SQLite migration)
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in checks.values() if isinstance(v, str)) else "degraded"

    return {
        "status": overall,
        "service": "nazar",
        "timestamp": datetime.now(IST).isoformat(),
        "checks": checks,
    }
```

### Acceptance Criteria

- [ ] Health check verifies storage, vector DB, LLM, and database
- [ ] Returns "degraded" if any check fails (not 500)
- [ ] Docker HEALTHCHECK uses this endpoint

---

## 25. P3 — Currency Configuration

### The Problem

Revenue, deal values, and pipeline values are hardcoded as `₹` (Indian Rupees) in:
- `Overview.jsx` — pipeline value display
- `Pipeline.jsx` — deal values
- `Analytics.jsx` — revenue charts
- `Contacts.jsx` — deal value column

### Fix

1. Add `currency` field to `config.json`: `{"currency": "INR", "currency_symbol": "₹"}`
2. Create shared formatter: `formatCurrency(amount, currency)` in `dashboard/src/utils/format.js`
3. Replace all hardcoded `₹` with the formatter
4. Add currency selector in `Settings.jsx`

### Acceptance Criteria

- [ ] Currency is configurable in settings
- [ ] All monetary values use the configured currency symbol
- [ ] At least USD, EUR, GBP, INR supported

---

## 26. P1 — Multi-Channel Support (Multiple Phone Numbers)

### Why This Is Critical

Today **one workspace = one WhatsApp phone number**. Many businesses need separate numbers for Sales, Support, and Marketing — each with its own persona, knowledge base, and conversation queue. Without this, businesses must create entirely separate workspaces per number, losing shared team/billing.

See `docs/channels.md` for the full design specification.

### Current State → Target

| Aspect | Current | Target |
|--------|---------|--------|
| Phone numbers per workspace | 1 (env var) | Multiple (DB table) |
| Webhook routing | Global `WA_PHONE_NUMBER_ID` | Extract `metadata.phone_number_id` → channel lookup |
| Contact uniqueness | `UNIQUE(workspace_id, phone)` | `UNIQUE(workspace_id, channel_id, phone)` |
| Messages | Workspace-scoped | Channel-scoped |
| Reply mode | Per-contact only | Channel default + per-contact override |
| Persona (SOUL.md) | Global | Per-channel `persona_prompt` override |
| Knowledge base | Global or campaign-scoped | + Channel-scoped |
| Opt-out | `(workspace_id, phone)` | `(workspace_id, channel_id, phone)` |
| Rate limiting | Global daily counter | Per-channel daily quota |
| Analytics | No channel dimension | Per-channel + aggregated |

### Implementation — ✅ Phase 1: Foundation (DONE)

#### 26.1 `core/workspace_context.py` — Channel Thread-Local

Added `set_channel()`, `get_channel()`, `clear_channel()`, and `clear_context()` following the same thread-local pattern used for workspace scoping.

#### 26.2 `core/database.py` — Schema & Migration

**New table: `channels`**
```sql
CREATE TABLE IF NOT EXISTS channels (
    id              TEXT PRIMARY KEY,           -- "ch_" + hex(12) or "default"
    workspace_id    TEXT NOT NULL,
    phone_number_id TEXT NOT NULL,              -- Meta phone number ID (globally unique)
    waba_id         TEXT DEFAULT '',
    access_token    TEXT NOT NULL DEFAULT '',   -- Per-number access token
    display_name    TEXT NOT NULL DEFAULT '',   -- "Support", "Sales", etc.
    persona_prompt  TEXT DEFAULT '',            -- System prompt override
    default_reply_mode TEXT DEFAULT 'auto_ai',
    kb_scope        TEXT DEFAULT 'global',
    is_primary      INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT DEFAULT NULL,
    UNIQUE(phone_number_id)
);
```

**Migration: `channel_id` added to existing tables:**
- `contacts`, `messages`, `handoff_states`, `optouts`, `reply_modes`
- `campaigns`, `campaign_contacts`, `ai_drafts`, `assignments`
- All default to `'default'` for backward compatibility
- New unique index: `ix_contacts_ws_ch_phone ON contacts(workspace_id, channel_id, phone)`

#### 26.3 `core/channel.py` — Channel CRUD Module (NEW)

Full CRUD operations:
- `create_channel()` — Register a phone number as a channel
- `get_channel()` / `get_channel_by_phone_number_id()` — Lookup
- `list_channels()` — List active (or all) channels per workspace
- `update_channel()` — Modify config (name, persona, reply mode, KB scope)
- `delete_channel()` — Soft-delete (is_active=0) or hard-delete
- `get_primary_channel()` — Get the workspace's primary channel
- `get_channel_config()` — Get persona/reply mode/KB config (no credentials)
- `get_channel_credentials()` — Get phone_number_id + access_token for sends
- `ensure_default_channel()` — Create backward-compat channel from env vars
- `channel_count()` — Count active channels

#### 26.4 `core/schemas.py` — Validation

- `CreateChannelRequest` — phone_number_id (required), access_token (required), display_name, etc.
- `UpdateChannelRequest` — Partial updates with validation on reply_mode

#### 26.5 `server.py` — API Endpoints & Webhook Routing

**New REST endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/channels` | List all channels in workspace |
| `POST` | `/api/channels` | Register a new channel (admin) |
| `GET` | `/api/channels/{id}` | Get channel details |
| `PUT` | `/api/channels/{id}` | Update channel config (admin) |
| `DELETE` | `/api/channels/{id}` | Soft/hard delete (admin) |
| `POST` | `/api/channels/{id}/verify` | Test Meta API connectivity |
| `GET` | `/api/channels/{id}/stats` | Contact/message/handoff counts |
| `GET` | `/api/contacts/{phone}/unified` | Cross-channel contact view |

**Webhook routing update:**
```
POST /webhook
  → extract value.metadata.phone_number_id
  → look up channel: SELECT * FROM channels WHERE phone_number_id = ?
  → set_workspace(channel.workspace_id)
  → set_channel(channel.id)
  → process messages as before
```

**Middleware:** `clear_context()` called after every request to prevent context leaking.

**Startup:** `ensure_default_channel()` called to auto-create the default channel from env vars.

#### 26.6 Tests: `tests/test_channels.py` (58 tests)

- **Context tests** (5): set/get/clear channel, independence from workspace, clear_context
- **Schema tests** (10): channels table exists, all column checks, channel_id on 7 tables, default value
- **CRUD tests** (25): create, duplicate detection, primary management, get, list, update, delete
- **Helper tests** (11): primary channel, config, credentials, channel_count
- **Default channel** (3): ensure_default_channel idempotency
- **Pydantic validation** (7): CreateChannelRequest/UpdateChannelRequest validation

### Implementation — Phase 2: Routing (Pending)

Wire channel credentials into outbound sends:
- Replace global `WA_API_URL` / `WA_ACCESS_TOKEN` with per-channel values from `get_channel_credentials()`
- `send_whatsapp_message()` uses channel from thread-local context
- `send_template_message()` uses channel credentials
- Campaign sends use the campaign's `channel_id` for outbound API calls

### Implementation — Phase 3: Core Scoping (Pending)

Make all subsystems channel-aware via `get_channel()`:
- `contact_manager.py` — All queries include `channel_id`
- `conversation.py` — `_build_system_prompt()` uses channel's `persona_prompt`
- `reply_mode.py` — Fallback chain: contact override → channel default → workspace default
- `optout_manager.py` — Per-channel opt-out
- `handoff_manager.py` — Per-channel handoff queue
- `analytics.py` — `channel_id` in all logged events
- `rate_limiter.py` — Per-channel daily quota
- `service_window.py` — Per (channel, contact) session windows

### Implementation — Phase 4: Features (Pending)

- `knowledge_base.py` — `channel_{id}` scope with fallback: campaign > channel > global
- `assignment_manager.py` — Channel-specific agent assignments
- Cross-channel contact view (unified phone number view)

### Implementation — Phase 5: UI (Pending)

- `dashboard/src/pages/Channels.jsx` — Channel management page
- `dashboard/src/components/Sidebar.jsx` — Channel selector dropdown
- Update existing pages to filter by selected channel

### Backward Compatibility

- **`channel_id = 'default'`** behaves exactly as pre-channel behavior
- **`get_channel()` returns `'default'`** when not explicitly set
- **Env vars still work:** `WA_PHONE_NUMBER_ID` / `WA_ACCESS_TOKEN` auto-create the default channel
- **All existing endpoints work** without `?channel_id=` param
- **All 641 pre-existing tests pass** with zero regressions

### Acceptance Criteria

- [x] `channels` table created with proper schema
- [x] `channel_id` column added to contacts, messages, handoff_states, optouts, reply_modes, campaigns, campaign_contacts, ai_drafts, assignments
- [x] Channel CRUD operations work (create, read, update, soft/hard delete)
- [x] Webhook extracts `phone_number_id` and routes to correct channel
- [x] Default channel auto-created from env vars on startup
- [x] All 699 tests pass (641 existing + 58 new)
- [ ] Outbound sends use per-channel credentials (Phase 2)
- [ ] All core modules query with `channel_id` (Phase 3)
- [ ] Per-channel persona, KB, rate limiting (Phase 3/4)
- [ ] Dashboard channel management UI (Phase 5)

---

## 27. Test Plan

> **Note:** Multi-channel tests are in `tests/test_channels.py` (58 tests covering context, schema, CRUD, helpers, backward compatibility, and Pydantic validation).

### Backend Tests to Add

| Test File | Coverage |
|---|---|
| `tests/test_reply_mode.py` | Reply mode CRUD, effective mode resolution, draft management |
| `tests/test_segmentation.py` | Segment evaluation with all operators, AND/OR logic |
| `tests/test_job_queue.py` | Job enqueue, progress, cancellation, concurrent jobs |
| `tests/test_rate_limiter.py` | Per-second and daily limit enforcement |
| `tests/test_opt_out.py` | STOP keyword detection, opt-out flow, campaign exclusion |
| `tests/test_webhook_security.py` | Signature verification, missing secret rejection |
| `tests/test_assignment.py` | Round-robin, least-busy, claim, transfer |
| `tests/test_knowledge_base.py` | Document add, chunk, query, campaign-scoped KB |
| `tests/test_audit.py` | Audit log creation, filtering |
| `tests/test_database.py` | SQLite CRUD, concurrent writes, migration |
| `tests/test_websocket.py` | WebSocket auth, event broadcast, reconnection |

### Integration Tests to Add

| Test | What it validates |
|---|---|
| Full webhook flow | Inbound message → AI reply → saved to DB → WebSocket broadcast |
| Campaign flow | Create → schedule → execute → rate-limited → track replies → analytics |
| Handoff flow | AI detects → trigger → assign agent → agent replies → resume bot |
| Draft flow | Inbound → AI draft generated → WebSocket notification → human approves → sent |
| Opt-out flow | Customer sends STOP → opted out → excluded from next campaign |

### Load Tests

Use `locust` or `ab`:
- 100 concurrent webhook requests → no data corruption
- 10K contact list load → < 500ms
- 50 simultaneous campaign sends → all complete correctly

---

## 28. Migration Strategy

> **Multi-channel migration:** The `_migrate_add_channel_id()` function in `core/database.py` handles adding `channel_id` columns to existing tables. Since there is no production data, this migration is for dev environments only. All existing data defaults to `channel_id = 'default'`.

### Phase 1: Non-breaking additions (week 1)
- Add SQLite alongside existing JSON (write to both, read from JSON)
- Add WebSocket (additive, doesn't change existing REST)
- Add Pydantic models (only adds validation, doesn't break existing callers)
- Fix webhook security (breaking, but security-critical)
- Fix branding (find-and-replace, no logic changes)

### Phase 2: Cutover (week 2)
- Run migration script: JSON → SQLite
- Switch reads from JSON to SQLite
- Test thoroughly
- Keep JSON files as backup for 30 days

### Phase 3: New features (weeks 3-4)
- Agent assignment, opt-out handling, campaign scheduling
- Media support, segmentation, structured KB
- Background job queue, rate limiting

### Phase 4: Polish (month 2)
- Audit logs, memory decay, Docker
- Frontend tests, error boundaries
- Pagination, currency config

---

## 29. Rollout Sequence

```
Week 1  ─── P0: SQLite migration + WebSocket + Webhook security + Template messages
Week 2  ─── P1: Job queue + Rate limiting + Opt-out handling
Week 3  ─── P1: Agent assignment + Campaign scheduling + Multi-channel foundation ✅
Week 4  ─── P1: Multi-channel routing + core scoping (Phases 2-3)
Week 5  ─── P2: Media support + Segmentation + Structured KB
Week 6  ─── P2: Webhooks/integrations + Campaign analytics + Multi-channel UI
Week 7  ─── P3: Pydantic validation + Pagination + Audit logs
Week 8  ─── P3: Docker + Tests + Memory decay + Cleanup
Week 9  ─── Testing, load testing, staging deployment, bug fixes
```

Each week ends with:
1. All existing tests still pass
2. New tests for new features pass
3. Manual smoke test of the full flow
4. Code review before merge

---

## Quick Reference: Files Modified Per Task

| Task | Files |
|---|---|
| SQLite | `core/database.py` (NEW), `core/db_migration.py` (NEW), `core/contact_manager.py`, `core/outbound.py`, `core/reply_mode.py`, `core/handoff_manager.py`, `server.py`, `requirements.txt` |
| WebSocket | `server.py`, `dashboard/src/hooks/useWebSocket.js` (NEW), `dashboard/src/pages/ConversationDetail.jsx`, `dashboard/src/pages/Campaigns.jsx`, `dashboard/src/context/AuthContext.jsx` |
| Template Campaigns | `core/outbound.py`, `server.py`, `dashboard/src/pages/Campaigns.jsx` |
| Webhook Security | `server.py` (lines 333-360), `core/onboarding.py` |
| Multi-Channel | `core/channel.py` (NEW), `core/workspace_context.py`, `core/database.py`, `core/schemas.py`, `server.py`, `tests/test_channels.py` (NEW), `docs/channels.md` |
| Job Queue | `core/job_queue.py` (NEW), `server.py` |
| Agent Assignment | `core/assignment_manager.py` (NEW), `server.py`, `dashboard/src/pages/ConversationDetail.jsx`, `dashboard/src/pages/Conversations.jsx` |
| Opt-out | `server.py`, `core/contact_manager.py`, `core/outbound.py` |
| Campaign Scheduling | `core/outbound.py`, `server.py`, `dashboard/src/pages/Campaigns.jsx` |
| Rate Limiting | `server.py` |
| Media Support | `server.py`, `core/contact_manager.py`, `dashboard/src/pages/ConversationDetail.jsx` |
| Segmentation | `core/segmentation.py` (NEW), `server.py`, `dashboard/src/pages/Campaigns.jsx` |
| Structured KB | `core/knowledge_base.py` (NEW), `core/conversation.py`, `dashboard/src/pages/KnowledgeBase.jsx`, `requirements.txt` |
| Outbound Webhooks | `core/webhook_dispatcher.py` (NEW), `server.py`, `dashboard/src/pages/Settings.jsx` |
| Campaign Analytics | `core/analytics.py`, `core/outbound.py`, `server.py`, `dashboard/src/pages/Campaigns.jsx` |
| Pydantic Validation | `core/schemas.py` (NEW), `server.py` (all endpoints) |
| Pagination | `core/contact_manager.py`, `core/outbound.py`, `server.py`, all frontend list pages |
| Token Revocation | `core/auth_manager.py`, `server.py` |
| Audit Log | `core/audit.py` (NEW), `server.py`, `dashboard/src/pages/AuditLog.jsx` (NEW) |
| Memory Decay | `core/customer_memory.py`, `server.py` |
| Docker | `Dockerfile` (NEW), `docker-compose.yml` (NEW), `.env.example` (NEW) |
| Error Boundaries | `dashboard/src/components/ErrorBoundary.jsx` (NEW), `dashboard/src/App.jsx` |
| Branding | `core/transcription.py`, `core/encryption.py`, `core/customer_memory.py` |
| Health Check | `server.py` |
| Currency | `dashboard/src/utils/format.js` (NEW), `dashboard/src/pages/Settings.jsx`, all pages with `₹` |
