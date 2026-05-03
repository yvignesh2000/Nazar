# Multi-Channel Support — Design Specification

> **Status:** Draft  
> **Sibling of:** `IMPLEMENTATION_PLAN.md`  
> **Scope:** Adding multi-phone-number (channel) support within a single workspace  
> **Data policy:** No production data. Clean schema change, no backfill migration.

---

## 1. Context & Current Architecture

Today **one workspace = one WhatsApp phone number**. The phone number is set via env vars (`WA_PHONE_NUMBER_ID`, `WA_ACCESS_TOKEN`) and stored as module-level globals in `server.py`. There's a nascent `additional_wa_numbers` array in `config.json`, but no subsystem actually uses it.

**Key architectural facts from the codebase:**

| Aspect | Current state | File |
|--------|--------------|------|
| **Workspace identity** | `workspace_id` in `workspaces.json` (SQLite-backed auth), thread-local via `workspace_context.py` | `core/workspace_context.py`, `data/auth/workspaces.json` |
| **Phone → workspace mapping** | Env var `WA_PHONE_NUMBER_ID` (single global). No lookup table. | `server.py:175` |
| **Contacts** | SQLite `contacts` table, keyed `(workspace_id, phone)` with `UNIQUE` constraint | `core/database.py`, `core/contact_manager.py` |
| **Messages** | SQLite `messages` table, keyed `(workspace_id, contact_id)` | `core/database.py` |
| **Reply mode** | SQLite `reply_modes` table, keyed `contact_id` (per-contact, not per-workspace) | `core/reply_mode.py` |
| **Opt-out** | SQLite `optouts` table, keyed `(workspace_id, phone)` | `core/optout_manager.py` |
| **Handoff** | SQLite `handoff_states` table, keyed `contact_id` | `core/handoff_manager.py` |
| **Analytics** | JSONL files in `data/analytics/{date}.jsonl`, no workspace/channel scoping | `core/analytics.py` |
| **Knowledge base** | ChromaDB vectors in `data/kb/`, scoped `global` or `campaign_{id}` | `core/knowledge_base.py` |
| **Webhook entry** | `POST /webhook` → no `phone_number_id` extraction from payload → uses global `WA_PHONE_NUMBER_ID` | `server.py:656` |
| **Outbound sends** | Global `WA_API_URL` built from single `WA_PHONE_NUMBER_ID` | `server.py:178`, `core/outbound.py` |

**Goal:** Allow a workspace to operate multiple WhatsApp phone numbers ("channels"), each with its own persona, conversations, and analytics — while sharing workspace-level auth, billing, and team.

**Hierarchy after this change:**
```
Workspace (tenant: auth, billing, team)
  └── Channel (phone number + persona + config)
        ├── Contacts         (same person can exist across channels)
        ├── Messages          (scoped to channel)
        ├── Reply Mode        (per-channel default, per-contact override)
        ├── Knowledge Base    (per-channel override or inherit workspace KB)
        ├── Analytics         (per-channel + aggregated at workspace)
        ├── Opt-out list      (per-channel — consent is per number)
        └── Handoff queue     (per-channel)
```

---

## 2. Functional Requirements

| ID | Requirement | Current State | Change Required |
|----|-------------|---------------|-----------------|
| FR1 | **Channel-scoped contacts** | `UNIQUE(workspace_id, phone)` in `contacts` table | Change to `UNIQUE(workspace_id, channel_id, phone)` — same person can be a contact on multiple channels |
| FR2 | **Channel-scoped messages** | `messages` table has `workspace_id` + `contact_id` | Add `channel_id TEXT NOT NULL DEFAULT 'default'` column to `messages` table |
| FR3 | **Per-channel persona / reply mode** | Reply mode is per-contact (`reply_modes` table). No per-channel default. SOUL.md is global. | Add channel-level `default_reply_mode` + `persona_prompt` (overrides SOUL.md). Per-contact overrides still work within a channel. |
| FR4 | **Unified contact view** | N/A — only one channel | New query: aggregate a phone number's interactions across all channels in a workspace |
| FR5 | **Per-channel knowledge base** | KB scoped as `global` or `campaign_{id}` | Add `channel_{id}` scope. Fall back to `global` if no channel KB exists. |
| FR6 | **Per-channel template management** | Templates stored in `templates.json`, not channel-aware | **Deferred.** Meta binds templates to WABA (not phone number). Note: when templates are synced via `meta_template_sync.py`, they're per-WABA already. |
| FR7 | **Per-channel human handoff** | `handoff_states` keyed by `contact_id` | Add `channel_id` to handoff state. Route handoff notifications to channel-specific team members. |
| FR8 | **Channel-level rate limiting** | `rate_limiter.py` is global (single daily counter) | Per-channel rate limit counters. Each channel gets its own daily quota. |
| FR9 | **Dual-view analytics** | JSONL logs in `data/analytics/`, no channel dimension | Add `channel_id` field to all logged events. Dashboard shows per-channel + aggregated views. |
| FR10 | **Per-channel opt-out** | `optouts` table keyed `(workspace_id, phone)` | Key becomes `(workspace_id, channel_id, phone)` — opt-out from one number doesn't opt out from another |
| FR11 | **Channel CRUD API** | `additional_wa_numbers` in `config.json` (unused) | New SQLite `channels` table + REST endpoints |
| FR12 | **Webhook routing** | Global `WA_PHONE_NUMBER_ID` env var; webhook doesn't inspect payload `phone_number_id` | Extract `metadata.phone_number_id` from webhook payload → look up `(workspace_id, channel_id)` |
| FR13 | **Channel management UI** | No UI | New dashboard page + channel selector in existing views |

---

## 3. Data Model

### 3.1 New SQLite Table: `channels`

```sql
CREATE TABLE IF NOT EXISTS channels (
    id              TEXT PRIMARY KEY,           -- "ch_" + hex(12)
    workspace_id    TEXT NOT NULL,
    phone_number_id TEXT NOT NULL,              -- Meta phone number ID (globally unique)
    waba_id         TEXT DEFAULT '',            -- WhatsApp Business Account ID
    access_token    TEXT NOT NULL,              -- Per-number access token (encrypted at rest)
    display_name    TEXT NOT NULL DEFAULT '',   -- "Support", "Sales", etc.
    persona_prompt  TEXT DEFAULT '',            -- System prompt override (empty = use SOUL.md)
    default_reply_mode TEXT DEFAULT 'auto_ai',  -- Channel default: auto_ai | human_only | ai_draft
    kb_scope        TEXT DEFAULT 'global',      -- 'global' or 'channel_{id}' for KB override
    is_primary      INTEGER DEFAULT 0,          -- boolean: is this the "main" number?
    is_active       INTEGER DEFAULT 1,          -- boolean: soft-disable
    created_at      TEXT NOT NULL,
    updated_at      TEXT DEFAULT NULL,
    UNIQUE(phone_number_id)
);
CREATE INDEX IF NOT EXISTS ix_channels_ws ON channels(workspace_id);
CREATE INDEX IF NOT EXISTS ix_channels_phone ON channels(phone_number_id);
```

### 3.2 Schema Changes to Existing Tables

```sql
-- contacts: allow same phone on different channels
ALTER TABLE contacts ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default';
DROP INDEX IF EXISTS ix_contacts_ws_phone;  -- old unique
CREATE UNIQUE INDEX ix_contacts_ws_ch_phone ON contacts(workspace_id, channel_id, phone);

-- messages: tag every message with its channel
ALTER TABLE messages ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS ix_messages_channel ON messages(channel_id);

-- handoff_states: scope handoff to channel
ALTER TABLE handoff_states ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default';

-- optouts: consent is per-channel
ALTER TABLE optouts ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default';
DROP INDEX IF EXISTS ix_optouts_ws_phone;  -- if exists
CREATE UNIQUE INDEX ix_optouts_ws_ch_phone ON optouts(workspace_id, channel_id, phone);

-- reply_modes: add channel dimension (contact override stays)
ALTER TABLE reply_modes ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default';
```

### 3.3 Migration Script

Since there's **no production data**, migration is for dev environments only:

```python
# scripts/migrate_add_channels.py
"""
Adds channel_id columns and creates channels table.
Safe to run multiple times (IF NOT EXISTS / ADD COLUMN guards).
"""

def migrate(conn):
    # 1. Create channels table
    conn.executescript(CHANNELS_TABLE_SQL)
    
    # 2. Add channel_id to existing tables
    for table in ['contacts', 'messages', 'handoff_states', 'optouts', 'reply_modes']:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass  # Column already exists
    
    # 3. Create default channel from env vars
    # (only if WA_PHONE_NUMBER_ID is set)
    
    # 4. Rebuild unique indexes
```

---

## 4. Routing Change (FR12)

### Current webhook flow
```
POST /webhook
  → parse JSON body
  → iterate entry[].changes[].value.messages[]
  → extract msg.from (phone number)
  → call _handle_text_message(phone, text, msg_id)
  → _handle_text_message uses global WA_PHONE_NUMBER_ID for replies
```

The webhook payload from Meta **already contains** `metadata.phone_number_id`:
```json
{
  "entry": [{
    "changes": [{
      "value": {
        "metadata": {
          "phone_number_id": "12345",
          "display_phone_number": "+1234567890"
        },
        "messages": [...]
      }
    }]
  }]
}
```

### New webhook flow
```
POST /webhook
  → parse JSON body
  → for each change:
      → extract value.metadata.phone_number_id
      → look up channel: SELECT * FROM channels WHERE phone_number_id = ? AND is_active = 1
      → if not found: log warning, skip
      → set_workspace(channel.workspace_id)
      → set_channel(channel.channel_id)   # NEW thread-local
      → for each message:
          → _handle_text_message(phone, text, msg_id)
          → uses channel's access_token + phone_number_id for replies
```

### Outbound change
```python
# Before (server.py:178)
WA_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# After — built per-request from channel context
def _get_wa_api_url(channel: dict) -> str:
    return f"https://graph.facebook.com/v21.0/{channel['phone_number_id']}/messages"

def _get_wa_headers(channel: dict) -> dict:
    return {"Authorization": f"Bearer {channel['access_token']}", "Content-Type": "application/json"}
```

---

## 5. workspace_context.py Extension

```python
# Add channel_id to thread-local context (same pattern as workspace_id)

_context = threading.local()

DEFAULT_WORKSPACE = "default"
DEFAULT_CHANNEL = "default"

def set_channel(channel_id: str):
    _context.channel_id = channel_id

def get_channel() -> str:
    return getattr(_context, "channel_id", DEFAULT_CHANNEL)

def clear_channel():
    _context.channel_id = DEFAULT_CHANNEL
```

All core modules that currently call `get_workspace()` will also call `get_channel()` where needed — no function signature changes required (same pattern that made multi-tenancy work).

---

## 6. File-by-File Touch List

| File | Change | FRs |
|------|--------|-----|
| **`core/channel.py`** | **New.** Channel dataclass, CRUD ops, lookup by `phone_number_id` | FR11 |
| **`core/workspace_context.py`** | Add `set_channel()`, `get_channel()`, `clear_channel()` | All |
| **`core/database.py`** | Add `channels` table to schema. Add `channel_id` columns via migration. | All |
| **`core/contact_manager.py`** | All functions accept `channel_id` (default from `get_channel()`). Update unique constraint. | FR1 |
| **`core/conversation.py`** | `_build_system_prompt()` uses channel's `persona_prompt` if set, else `SOUL.md` | FR3 |
| **`core/reply_mode.py`** | Add `get_channel_default_mode()`. `get_effective_reply_mode()` checks: contact override → channel default → workspace default. | FR3 |
| **`core/knowledge_base.py`** | Add `channel_{id}` scope alongside `global` and `campaign_{id}`. Fallback chain: `campaign > channel > global`. | FR5 |
| **`core/optout_manager.py`** | All queries add `channel_id` to WHERE clause. `can_message()` checks per-channel opt-out. | FR10 |
| **`core/analytics.py`** | `log_event()` includes `channel_id`. New aggregation functions: `get_channel_analytics()`, `get_workspace_analytics_aggregated()`. | FR9 |
| **`core/handoff_manager.py`** | `trigger_handoff()` stores `channel_id`. Handoff queue filterable by channel. | FR7 |
| **`core/rate_limiter.py`** | `WARateLimiter` becomes per-channel. Factory: `get_rate_limiter(channel_id)`. | FR8 |
| **`core/outbound.py`** | Send functions use channel's `phone_number_id` + `access_token` instead of globals. | FR1, FR12 |
| **`core/service_window.py`** | `compute_window()` accepts `channel_id` — session window is per (channel, contact). | FR7 |
| **`core/assignment_manager.py`** | Add `channel_id` to assignments. Agents can be assigned to specific channels. | FR7 |
| **`core/audit.py`** | `log_audit()` includes `channel_id` in audit trail. | All |
| **`core/schemas.py`** | Add Pydantic models: `CreateChannelRequest`, `UpdateChannelRequest`. | FR11 |
| **`server.py`** | (1) Webhook: extract `metadata.phone_number_id`, look up channel. (2) Replace global `WA_API_URL`/`WA_ACCESS_TOKEN` with per-channel values. (3) New CRUD endpoints under `/api/channels`. (4) Set `channel_id` in middleware. | FR11, FR12 |
| **`dashboard/src/`** | New `Channels.jsx` page. Channel selector in `Sidebar.jsx`. Filter existing pages by channel. | FR13 |

---

## 7. API Endpoints (FR11)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/channels` | Create a channel (registers a phone number) |
| `GET` | `/api/channels` | List all channels in current workspace |
| `GET` | `/api/channels/{ch_id}` | Get channel details |
| `PUT` | `/api/channels/{ch_id}` | Update channel config (name, persona, reply mode, KB scope) |
| `DELETE` | `/api/channels/{ch_id}` | Deactivate channel (soft delete, `is_active=0`) |
| `POST` | `/api/channels/{ch_id}/verify` | Test connectivity (send a test API call to Meta) |
| `GET` | `/api/contacts/{phone}/unified` | Cross-channel contact view (FR4) |

All existing endpoints (`/api/contacts`, `/api/conversations`, etc.) gain an optional `?channel_id=` query param. If omitted, uses the thread-local channel from context (set by auth middleware based on the user's selected channel in the dashboard).

---

## 8. Cross-Channel Contact View (FR4)

```sql
-- Find all channel interactions for a phone number within a workspace
SELECT 
    ch.display_name AS channel_name,
    c.channel_id,
    c.pipeline_stage,
    c.lead_score,
    c.last_contacted_at,
    c.last_replied_at,
    (SELECT COUNT(*) FROM messages m WHERE m.contact_id = c.id) AS message_count
FROM contacts c
JOIN channels ch ON c.channel_id = ch.id
WHERE c.workspace_id = ? AND c.phone = ?
ORDER BY c.last_replied_at DESC;
```

---

## 9. Conversation Engine Changes (FR3)

```python
# core/conversation.py — _build_system_prompt() modification

def _build_system_prompt(contact, memory_context, knowledge_base, config, campaign_kb=""):
    # NEW: check for channel-level persona
    from workspace_context import get_channel
    from channel import get_channel_config
    
    channel_config = get_channel_config(get_channel())
    
    if channel_config and channel_config.get("persona_prompt"):
        soul = channel_config["persona_prompt"]  # Use channel persona
    else:
        soul = _load_soul()  # Fall back to SOUL.md
    
    # ... rest of prompt building unchanged
```

---

## 10. Implementation Order

```
Phase 1: Foundation (no behavior change)
  ├── core/channel.py — data model + CRUD
  ├── core/database.py — channels table + ALTER TABLE migrations
  ├── core/workspace_context.py — add channel thread-local
  ├── scripts/migrate_add_channels.py
  └── tests/test_channels.py

Phase 2: Routing (messages start flowing per-channel)
  ├── server.py — webhook phone_number_id extraction + channel lookup
  ├── server.py — replace global WA_API_URL with per-channel
  ├── core/outbound.py — use channel credentials
  └── server.py — channel CRUD API endpoints

Phase 3: Core scoping (subsystems become channel-aware)
  ├── core/contact_manager.py — channel_id in all ops
  ├── core/conversation.py — per-channel persona
  ├── core/reply_mode.py — channel default mode
  ├── core/optout_manager.py — per-channel consent
  ├── core/handoff_manager.py — per-channel handoff
  └── core/analytics.py — per-channel metrics

Phase 4: Features
  ├── core/knowledge_base.py — per-channel KB scope
  ├── core/rate_limiter.py — per-channel limits
  ├── Cross-channel contact view (FR4)
  └── core/assignment_manager.py — channel assignments

Phase 5: UI
  ├── dashboard/src/pages/Channels.jsx — channel management
  ├── dashboard/src/components/Sidebar.jsx — channel selector
  └── Update existing pages to filter by selected channel
```

---

## 11. Backward Compatibility

- **Default channel:** When `channel_id = 'default'`, the system behaves exactly as today (global env vars). This means the migration is a no-op for existing dev setups.
- **Thread-local fallback:** `get_channel()` returns `'default'` when not set, so all existing code paths work unchanged until channel support is explicitly activated.
- **Env vars still work:** `WA_PHONE_NUMBER_ID` / `WA_ACCESS_TOKEN` env vars are used to auto-create the "default" primary channel on first boot.
- **API backward compat:** All existing endpoints work without `?channel_id=` param — they'll use the default channel.

---

## 12. Open Questions

1. **Channel limit per workspace?** Suggest: 10 channels per workspace initially (configurable per plan in billing).
2. **Soft-delete vs hard-delete?** Proposal: soft-delete only (`is_active=0`). Hard delete requires wiping messages/contacts which is destructive.
3. **Cross-channel contact merging?** FR4 provides read-only unified view. Explicit merge (combining two channel-contacts into one) is out of scope for this phase.
4. **Per-channel webhook URL?** Meta uses one webhook URL per app, not per number — all numbers route to the same `/webhook`. The `phone_number_id` in the payload is how we disambiguate. **No change needed on Meta's side.**
5. **Access token storage?** `channels.access_token` contains a Meta token. Should we encrypt it at rest (like we do for conversation content) or is DB-level encryption sufficient? Suggest: encrypt with workspace-level key.

---

## 13. Non-Goals (This Phase)

- Template management (FR6) — deferred, templates are per-WABA not per-number
- Multi-WABA support — one WABA per workspace for now
- Channel transfer (moving a phone number between workspaces)
- Real-time channel switching in active conversations
- Separate SOUL.md files per channel (using `persona_prompt` field instead)
