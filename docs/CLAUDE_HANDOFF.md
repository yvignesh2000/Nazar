# Nazar Claude Handoff

This document is the engineering handoff for continuing Nazar on Claude.

It is meant to answer:
- what Nazar is
- how it is currently built
- what infrastructure/runtime it uses
- what has already been implemented
- what is committed versus still local
- what the next engineer should do next

## 1. Repository and Branch State

Repository:
- `https://github.com/yvignesh2000/Nazar`

Primary working branch:
- `codex/product-foundation`

Latest pushed checkpoint:
- commit `49cc865`
- message: `Add team auth and onboarding foundation`

Recent important commits:
- `49cc865` Add team auth and onboarding foundation
- `dc93b7d` Advance product shell and document current state
- `a82c3f9` Stabilize channels and restructure product shell
- `24dcdb4` Advance AI memory and campaign builder
- `cee5a73` Add public privacy and data deletion pages

Current known local-only change not included in the pushed checkpoint:
- [`nazar/core/contact_manager.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/contact_manager.py)

That file was intentionally not committed in the last checkpoint. Claude should inspect `git status` before making assumptions.

## 2. Product Direction

Nazar is being built as an AI-native sales operating system.

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
- run outbound sales campaigns
- capture inbound replies
- classify and move leads through the pipeline with AI
- help sales reps close deals faster

## 3. Current Runtime / Hosting State

### Local runtime

Nazar is currently being run locally on the developer machine.

Current app runtime:
- API server on `http://localhost:8002`
- worker process running separately

This is not a deployed VPS environment yet.

### Database

Current storage:
- SQLite

Database file:
- [`nazar/data/nazar.db`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/data/nazar.db)

The codebase is already structured around SQLAlchemy models and can later move to Postgres more cleanly than the old JSON/file-only shape.

### Public hosting

No stable production hosting is set up yet.

Historically during testing:
- Cloudflare tunnel / temporary public URL was used for webhook testing
- Meta WhatsApp webhook setup was tested against temporary public URLs

Current practical truth:
- local development is the main runtime
- there is no final VPS/domain deployment yet

### Channel testing

WhatsApp:
- backend and settings diagnostics exist
- Meta sandbox restrictions still make testing awkward without a proper dedicated business number

Telegram:
- added as a real testing transport
- currently the easiest real end-to-end transport for product behavior testing

## 4. Infrastructure and Technical Stack

Backend:
- FastAPI
- SQLAlchemy
- aiohttp for outbound HTTP calls
- uvicorn for serving

Frontend:
- single-file vanilla JS dashboard in [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html)

Worker:
- background Python worker in [`nazar/worker.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/worker.py)

AI:
- primary reply engine uses [`nazar/agent/SOUL.md`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/agent/SOUL.md)
- LLM routing in [`nazar/core/llm_router.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/llm_router.py)
- classification in [`nazar/core/ai_classifier.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/ai_classifier.py)

Memory:
- per-contact memory in [`nazar/core/customer_memory.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/customer_memory.py)
- DB-backed fallback is active
- vector/Chroma path is not the final production-grade memory architecture yet

Channels:
- WhatsApp in [`nazar/server.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/server.py)
- Telegram adapter in [`nazar/core/telegram_adapter.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/telegram_adapter.py)

Policies and routing:
- [`nazar/core/policy_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/policy_store.py)

Templates:
- [`nazar/core/template_manager.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/template_manager.py)

Analytics:
- [`nazar/core/analytics_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/analytics_store.py)

Audit trail:
- [`nazar/core/audit_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/audit_store.py)

Workspace config:
- [`nazar/core/workspace_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/workspace_store.py)

## 5. Current Product State

### Working product areas

#### Conversations
- inbound messages create or update contacts and conversations
- manual rep replies work
- bot replies work when routing and channel transport allow them
- assignment works
- notes work
- AI summary / routing decision / deal controls sidebar exists
- live updates are driven by WebSockets

#### Campaigns
- campaigns can be created and named
- audiences can be selected by stage and group
- reusable audiences exist
- template or custom-copy campaigns are supported
- per-campaign reply handling exists
- campaign outcome and reply metrics exist

#### Contacts
- contacts are the system of record
- stage, deal value, source, and grouping exist
- groups are channel-independent

#### Insights
- objection summary
- risk framing
- conversion likelihood
- next best action

#### Notifications
- live dropdown notifications exist

### Transitional / still rough

- onboarding UX is now real in foundation form, but still needs polish
- team management currently lives inside Settings, not yet a first-class product surface
- memory is working, but still not the final production-grade vector architecture
- WhatsApp is integrated, but constrained by Meta sandbox/testing realities
- Telegram is the practical real transport for current product validation

## 6. New Team Access and Onboarding Foundation

This is the biggest recent architectural change.

### What changed

The old auth model:
- one shared `NAZAR_API_KEY`
- login creates a session for the first workspace member

The new auth model:
- roles:
  - `Owner`
  - `Sales Lead`
  - `Sales Rep`
- email invite + magic link login
- one workspace per customer
- owner-first onboarding

### Backend additions

New DB entities:
- `workspace_invites`
- `auth_magic_links`
- `workspace_onboarding_state`

Main implementation files:
- [`nazar/core/auth_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/auth_store.py)
- [`nazar/core/db.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/db.py)
- [`nazar/core/workspace_store.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/workspace_store.py)
- [`nazar/core/mailer.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/mailer.py)

New API surfaces:
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

### Role model

Owner:
- full control over workspace, channels, AI setup, team management, templates, campaigns, analytics

Sales Lead:
- can operate campaigns, team operations, conversations, contacts, insights, analytics
- should not control owner-level workspace/channel secrets

Sales Rep:
- works conversations, contacts, follow-ups, insights, and campaigns
- cannot manage workspace/channel/auth configuration

### Frontend additions

In [`nazar/frontend/index.html`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/frontend/index.html):
- auth overlay
- workspace bootstrap flow
- magic-link handling from URL params
- invite acceptance handling from URL params
- onboarding overlay
- team management inside Settings
- role-aware nav visibility

### Mail delivery

Provider choice:
- Resend

Implementation:
- [`nazar/core/mailer.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/mailer.py)

Behavior:
- if Resend env is missing, mail falls back to dev mode
- dev mode returns direct invite/magic-link URLs in API responses
- this was done so development can continue without blocking on email infra

## 7. Environment and Secrets

Current runtime expects `.env` under:
- [`nazar/.env`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/.env)

Important variables already used in the codebase:
- `DATABASE_URL`
- `NAZAR_ALLOW_SCHEMA_CREATE`
- `NAZAR_API_KEY`
- `NAZAR_APP_URL`
- `NAZAR_WORKSPACE_SLUG`
- `NAZAR_WORKSPACE_NAME`
- `NAZAR_OWNER_NAME`
- `NAZAR_OWNER_EMAIL`
- `WA_PHONE_NUMBER_ID`
- `WA_ACCESS_TOKEN`
- `WA_VERIFY_TOKEN`
- `OPENROUTER_API_KEY`
- `TELEGRAM_BOT_TOKEN` or equivalent Telegram token env used by the adapter
- `RESEND_API_KEY`
- `RESEND_FROM_EMAIL`

Claude should inspect:
- [`nazar/server.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/server.py)
- [`nazar/core/telegram_adapter.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/telegram_adapter.py)
- [`nazar/core/mailer.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/mailer.py)

## 8. What Was Verified

Verified in isolated API tests on a temporary SQLite DB:
- owner bootstrap creates owner session and onboarding state
- magic-link request works
- magic-link verification creates valid session
- invite create works
- invite accept works
- role promotion works
- deactivation revokes access
- Sales Rep is blocked from owner-only config endpoints

Static checks passed:
- Python compile checks for the modified backend files
- frontend JS syntax checks by extracting the inline script from `index.html`

## 9. Current Known Gaps

These are the main things still needing work after the auth/onboarding foundation:

1. Onboarding UX polish
- current onboarding is functional but still lightweight
- steps still guide the user into the right screens rather than embedding all actions elegantly

2. Team surface
- team management is in Settings
- likely needs to become a stronger first-class operational surface later

3. Role-aware product tightening
- role gating is in place, but product copy and UX should be tightened further for each persona

4. WhatsApp finalization
- Meta sandbox still limits smooth end-to-end testing
- proper dedicated business number and final deploy path still needed

5. Memory architecture
- DB fallback is active
- not yet production-grade vector retrieval architecture

6. Local-only deployment
- final VPS/domain/systemd/Nginx deployment is not done yet

## 10. How Claude Should Continue

Recommended immediate order:

1. Polish owner onboarding
- make each step more self-contained
- improve transition between bootstrap, channel setup, business knowledge, team invite, first campaign

2. Tighten role-aware UX
- ensure Sales Rep never sees owner-only settings
- ensure Sales Lead has the right operational view

3. Improve team management
- cleaner invite/member layout
- stronger statuses and invite lifecycle clarity

4. Continue sellability work
- campaign operations
- team operations
- insights quality

## 11. Suggested Claude Prompt

Use something like this:

> Continue on branch `codex/product-foundation` from commit `49cc865`.
>
> Nazar is an AI-native sales operating system. The product shell, campaigns, conversations, insights, Telegram transport, and a new auth/onboarding foundation are already in place.
>
> Read:
> - `docs/PRODUCT_STATE.md`
> - `docs/CLAUDE_HANDOFF.md`
>
> Current auth/onboarding foundation:
> - roles are `Owner`, `Sales Lead`, `Sales Rep`
> - login is invite-by-email + magic link
> - owner-first onboarding is implemented in a first working form
> - team management currently lives in Settings
>
> Current priorities:
> 1. polish owner onboarding
> 2. tighten role-aware UX and permissions in the product shell
> 3. improve the team management product surface
> 4. continue toward sellable team operations
>
> Important:
> - preserve the current single-workspace-per-customer assumption
> - preserve bearer session behavior already used across the app
> - do not reintroduce the shared API-key login as the main product auth path
> - keep the product operator-first, compact, and commercially credible

## 12. Final Practical Notes

- The app has been run locally on `localhost:8002`
- The worker runs separately
- Telegram is currently the easiest real transport for testing
- WhatsApp is strategically important but operationally harder right now
- Before continuing, Claude should run:
  - `git status`
  - verify whether [`nazar/core/contact_manager.py`](/Users/vignesh-12220/Documents/App Development/NAZAR/nazar/core/contact_manager.py) still has local-only changes
  - verify the current local runtime state before assuming the app is clean

