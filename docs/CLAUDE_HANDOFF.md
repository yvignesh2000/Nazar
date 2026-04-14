# Nazar Claude Handoff

This is the current engineering handoff for continuing Nazar.

It is written to let Claude pick up the repo, understand what already exists, and continue building without re-discovering the product and runtime from scratch.

## 1. Repo and Branch

Repository:
- `https://github.com/yvignesh2000/Nazar`

Main branch in use:
- `codex/product-foundation`

Latest major milestones:
- **Phase 1 Infrastructure:** Migrated from local SQLite + Cloudflare tunnels to a robust cloud setup (Docker, Postgres, Railway).
- **Core Engine:** Campaign-level knowledge packs, AI-native reply generation, and per-contact vector memory are functional.

Claude should still run:
- `git status`
- `git log --oneline -n 10`

before making assumptions.

## 2. Product Direction

Nazar is being built as an AI-native sales operating system for chat-first teams.

Target information architecture:
1. Dashboard
2. Campaigns
3. Contacts
4. Pipelines
5. Conversations
6. Insights
7. Analytics

Admin/config surfaces:
- AI Setup
- Settings

Core promise:
- launch outbound campaigns
- capture inbound replies
- qualify and route leads with AI
- move leads through pipeline
- help reps close with context, risk, and next-best-action

## 3. Current Runtime / Hosting

### Cloud Deployment (Phase 1 Complete)
Nazar has been structurally migrated from a local prototype to a production-ready infrastructure:
- **Hosting:** Deployed on Railway.app.
- **Database:** Migrated to Managed PostgreSQL.
- **Containerization:** Repackaged using `Dockerfile` (API) and `Dockerfile.worker` (Background jobs). A `docker-compose.yml` supports local dev parity.
- **Stability:** Added a `/health` endpoint and fixed nginx WebSocket protocols for live UI updates.

### Local runtime
When running locally:
- Use `docker compose up --build` to run Postgres, API (`localhost:8002`), and Worker simultaneously.
- Configuration is in `nazar/.env` (cloned from `nazar/.env.template`).

## 3.5. Product Strategy & Active Roadmap
Nazar is explicitly being built as a **SaaS product** (not a managed service). The goal is to reach a self-serve tier similar to WATI/Interakt, but with superior AI capabilities. 

We have just completed Phase 1 (Infrastructure) and are moving iteratively through the following approved roadmap:

1. **Phase 2: Core SaaS Foundation (Multi-tenancy) -> ACTIVE**
   - Immediate next step. Strict data isolation by `workspace_id` across all tables.
   - Without this, onboarding multiple paying customers is impossible.
2. **Phase 3: The "Must-Haves" (Automation & Templates)**
   - Drip sequences and follow-ups.
   - WhatsApp template creation and approval manager.
3. **Phase 4: Monetization & Self-Serve (Billing)**
   - Automated onboarding / embedded signup.
   - Stripe/Razorpay integration and workspace usage quotas.
4. **Phase 5: The "Moat" (Visual Flow Builder & SPA Frontend)**
   - Drag-and-drop Visual Flow Builder.
   - Transitioning `index.html` to a React/Vite SPA.

### Current channel state

WhatsApp:
- integrated
- settings and diagnostics exist in product
- still painful to validate because of Meta sandbox / number constraints

Telegram:
- practical live test channel
- easier than WhatsApp for end-to-end testing right now

## 4. Stack

Backend:
- FastAPI
- SQLAlchemy
- aiohttp
- uvicorn

Frontend:
- single-file vanilla JS app in:
  - [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html)

Worker:
- [`nazar/worker.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/worker.py)

AI:
- persona / behavior source:
  - [`nazar/agent/SOUL.md`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/agent/SOUL.md)
- reply engine:
  - [`nazar/core/conversation.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/conversation.py)
- classifier:
  - [`nazar/core/ai_classifier.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/ai_classifier.py)
- router:
  - [`nazar/core/llm_router.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/llm_router.py)

Memory:
- [`nazar/core/customer_memory.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/customer_memory.py)

Policies / routing:
- [`nazar/core/policy_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/policy_store.py)

Templates:
- [`nazar/core/template_manager.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/template_manager.py)

Workspace config:
- [`nazar/core/workspace_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/workspace_store.py)

Auth / invites:
- [`nazar/core/auth_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/auth_store.py)

Campaign knowledge:
- [`nazar/core/campaign_knowledge.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/campaign_knowledge.py)

## 5. What the Product Already Does

### Conversations
- inbound messages create/update contacts and conversations
- manual rep sends work
- AI replies / AI draft flows exist
- assignment works
- notes work
- sidebar includes:
  - what Nazar sees
  - why routed this way
  - next best action
  - deal details
  - deal controls

### Campaigns
- campaigns can be named
- audience by stage and group
- reusable audiences
- template or custom copy
- per-campaign reply handling
- campaign metrics and drill-down
- open replies for a specific campaign

### Contacts
- system of record for leads/customers
- stage, group, score, source, deal value
- group assignment is channel-independent

### Insights
- objection summary
- risk level and reason
- conversion likelihood
- next best action

### Analytics
- message performance
- pipeline conversion snapshot
- team workload
- operating recommendations

### Live product behavior
- WebSocket-based live UI refresh
- no more polling flicker

### Team access foundation
- real roles
- magic link auth
- invites
- onboarding state

## 6. Auth / Team / Onboarding Foundation

This is the biggest architectural change from the older MVP.

### Roles

Normalized roles:
- `owner`
- `sales_lead`
- `sales_rep`

User-facing labels:
- Owner
- Sales Lead
- Sales Rep

### DB additions

Added:
- `WorkspaceInvite`
- `AuthMagicLink`
- `WorkspaceOnboardingState`

Main schema file:
- [`nazar/core/db.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/db.py)

### Auth APIs

Added:
- `GET /api/public/bootstrap-state`
- `POST /api/workspace/bootstrap`
- `POST /api/auth/request-magic-link`
- `POST /api/auth/verify-magic-link`
- `GET /api/onboarding`
- `PATCH /api/onboarding`
- `GET /api/team/invites`
- `POST /api/team/invites`
- `POST /api/team/invites/{id}/resend`
- `POST /api/team/invites/{id}/revoke`
- `POST /api/team/invites/{token}/accept`
- `PATCH /api/team/members/{user_id}`
- `POST /api/team/members/{user_id}/deactivate`

### Frontend

Implemented in:
- [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html)

Includes:
- auth overlay
- bootstrap workspace flow
- magic-link handling from URL params
- invite-accept flow from URL params
- onboarding overlay
- team management UI in Settings
- role-aware nav visibility

### Important current testing behavior

Onboarding is currently bypassed in the frontend so testers can use the product without being blocked by setup flow.

This bypass is in:
- [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html)

Behavior:
- onboarding state still loads
- blocking overlay does not auto-open by default

It can be re-enabled via localStorage:
- set `nazar_bypass_onboarding = '0'`

And bypassed again by removing that key or setting any other value.

## 7. Campaign Knowledge Packs

This is the most recent major product addition.

### What it does

Each campaign can now have its own:
- notes
- AI instruction
- attached files

This exists because campaign replies should use:
1. global business knowledge
2. campaign-specific knowledge
3. contact memory
4. conversation history

### Backend

Storage module:
- [`nazar/core/campaign_knowledge.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/campaign_knowledge.py)

Features:
- stores campaign notes
- stores campaign instruction
- stores attached files under:
  - [`nazar/data/campaign_knowledge`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/data/campaign_knowledge)
- extracts text from:
  - txt / md / csv / json
  - docx (basic zip/xml extraction)
  - pdf (only if `pypdf` is installed)

### API

Added:
- `GET /api/campaigns/{campaign_key}/knowledge`
- `PUT /api/campaigns/{campaign_key}/knowledge`
- `POST /api/campaigns/{campaign_key}/knowledge/files`
- `DELETE /api/campaigns/{campaign_key}/knowledge/files/{file_id}`

### Important implementation detail

File upload is currently JSON/base64, not multipart.

Reason:
- this environment did not have `python-multipart`
- I intentionally avoided introducing a dependency requirement just to make campaign file uploads work

This means frontend file upload:
- reads files with `FileReader`
- sends them as base64 JSON

### Prompt integration

Campaign context is injected into reply generation through:
- [`nazar/core/conversation.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/conversation.py)

And used by:
- worker replies
- worker AI-assist drafts
- simulator campaign/inbound testing

### UI

Campaign sheet now includes:
- Campaign notes
- AI instruction
- file upload
- attachment list

History/detail now indicates whether a campaign had a knowledge pack.

Current limitation:
- PDF uploads are stored correctly, but text extraction depends on `pypdf`
- if `pypdf` is not installed, PDF files will still upload but may not contribute extracted text to prompts

## 8. WhatsApp and Telegram

### WhatsApp

Implemented in:
- [`nazar/server.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/server.py)

Current truth:
- config and diagnostics are exposed in the product
- auth/token errors are surfaced properly now
- full live testing is still constrained by Meta sandbox / number ownership realities

### Telegram

Telegram was added as the practical test transport.

Relevant files:
- [`nazar/core/telegram_adapter.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/telegram_adapter.py)
- [`nazar/worker.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/worker.py)

Current value:
- real send / receive testing
- real inbox behavior
- real campaign reply loop

## 9. Memory State

There is real per-contact memory, but the architecture is still transitional.

Current status:
- DB-backed fallback is active
- not yet final production-grade vector architecture

Practical implication:
- product behavior is good enough for MVP use
- memory is a real feature
- but retrieval architecture likely needs a later cleanup / Postgres+vector plan

## 10. Product Copy Rewrite

The product text was heavily rewritten to stop sounding like an internal workflow engine.

Main changes:
- operator-first copy
- removed a lot of system/internal vocabulary
- better sales framing across:
  - Campaigns
  - Conversations
  - Insights
  - Analytics
  - Needs Attention
  - AI Setup
  - Settings
  - auth/onboarding

Main file:
- [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html)

## 11. Current Gaps / What Still Needs Work

### Product / UX
- onboarding still needs a polished production path
- team management should move out of Settings into a stronger surface later
- some screens still need visual tightening, especially where metrics/cards are sparse

### Commercial
- campaign operations still need richer premium features:
  - follow-up sequences
  - better campaign knowledge preview
  - stronger attribution / analytics
  - maybe A/B later

### Channel setup
- WhatsApp still needs a clean production-grade path with a proper dedicated number

### Memory
- still not final-grade architecture

## 12. Recommended Next Steps for Claude

If continuing product work, the best order is:

1. tighten campaign knowledge UX
- show better preview of attached knowledge
- show when replies used campaign knowledge
- make campaign detail surface this better

2. premium campaign ops
- follow-up sequences / drips
- better audience segmentation
- better campaign performance views

3. team operating layer
- inbox aging / SLA
- clearer ownership load
- better manager visibility

4. onboarding polish
- now that the foundation exists, make it trustworthy and non-blocking

5. WhatsApp production path
- only after the team decides how they want to handle real number ownership

## 13. Good Starting Prompt for Claude

Use this prompt:

```text
Continue Nazar on branch codex/product-foundation.

Context:
- Nazar is an AI-native sales operating system for chat-first sales teams.
- The current app is a single-file frontend in nazar/frontend/index.html with a FastAPI backend and worker.
- Main product surfaces are Dashboard, Campaigns, Contacts, Pipelines, Conversations, Insights, Analytics.
- Team auth/onboarding foundation already exists: owner/sales_lead/sales_rep, invites, magic links, onboarding state.
- Onboarding is currently bypassed in the frontend for testing, but the backend state still exists.
- Telegram is the practical live test channel right now. WhatsApp is integrated but constrained by Meta sandbox realities.
- Campaign-specific knowledge packs were just added. They support notes, AI instruction, and uploaded files, and campaign replies now use this context in the prompt.

What to do next:
1. Tighten the campaign knowledge experience in the UI and campaign detail view.
2. Keep the product operator-first; avoid exposing backend/internal concepts in the UI.
3. Preserve current architecture unless there is a strong product reason to refactor it.
4. Prefer improving sellability, clarity, and reliability over adding random new surfaces.
5. Explain changes in product language, not only engineering language.
```
