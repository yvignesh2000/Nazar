# Nazar Product State

This document explains what Nazar has already built, how the product currently works, and which parts are already functional versus transitional.

## Product Positioning

Nazar is being built as an AI-native sales operating system, not just a messaging dashboard.

The current target product structure is:

1. Dashboard
2. Campaigns
3. Contacts
4. Pipelines
5. Conversations
6. Insights
7. Analytics

The core commercial idea is:
- run outbound campaigns
- capture inbound replies
- move leads through the pipeline automatically with AI
- help the sales team close deals faster

## What Nazar Does Today

### 1. Conversations

Nazar has a working conversation inbox.

It supports:
- inbound messages creating or updating contacts
- per-contact conversations
- manual replies from a rep
- AI replies when allowed
- AI-draft-for-human workflows
- human handoff
- assignment
- status handling like `needs_reply`, `open`, `snoozed`, `closed`
- internal notes

The right-side conversation panel now focuses on:
- AI summary
- routing decision
- what to do next
- deal controls

### 2. Campaigns

Nazar has a working campaign engine.

It supports:
- creating campaigns
- naming campaigns
- choosing audience by stage and contact group
- saving reusable audiences
- template or custom-copy campaigns
- per-campaign reply handling
- campaign history
- campaign detail metrics

Campaign reply handling is configured per campaign, not globally.

That means one campaign can be:
- AI replies automatically
- team reviews AI draft
- team replies first
- team only

### 3. Contacts

Contacts are the system of record in Nazar.

Everything hangs off the contact:
- campaigns target contacts
- conversations belong to contacts
- pipeline stage lives on contacts
- lead score lives on contacts
- AI memory is stored per contact
- insights are generated per contact

Contacts currently support:
- manual creation
- stage tracking
- deal value
- source tracking
- groups
- tags-backed grouping
- filtering by stage and group

Groups are channel-independent.

That means a contact can be grouped regardless of whether it came from:
- Telegram
- WhatsApp
- manual entry
- import

### 4. Pipelines

Nazar has a working pipeline view and pipeline-aware CRM model.

Current stages:
- New
- Qualified
- Proposal
- Negotiation
- Won
- Lost

Nazar can:
- move contacts between stages
- use stage in campaign targeting
- use stage in routing logic
- use stage in analytics and insights

### 5. Insights

Nazar has an initial insights layer.

It already surfaces:
- high-score contacts
- risk framing
- AI summaries
- recommended next action

This is still early compared with the long-term vision, but the surface exists and is wired to real data.

### 6. Analytics

Nazar has an initial analytics layer.

It currently shows:
- message performance
- queue load
- campaign replies
- bot vs human sends
- pipeline distribution
- AI recommendations

### 7. Notifications

Nazar now has live in-product notifications.

Current notification sources:
- needs reply
- AI drafts ready
- unassigned conversations
- campaign replies

Notifications open the relevant inbox state.

### 8. Live Updates

The app now uses WebSockets for live updates instead of timer polling.

This was added to avoid:
- manual refresh
- 2-3 second flicker
- stale conversation state

Live updates currently cover:
- conversations
- overview/dashboard state
- notifications

## AI Layer

Nazar has multiple AI responsibilities today.

### Reply generation

Reply generation uses:
- `SOUL.md`
- knowledge base
- recent conversation context
- per-contact memory

This is the main bot reply engine.

### Classification

Inbound messages can be classified into:
- intent
- stage recommendation
- lead score
- ownership recommendation

The current product decision is:
- AI stage changes auto-apply
- manual override is still allowed

### Routing

Routing decides who handles a conversation:
- AI automatically
- human first
- AI draft for human
- manual only

Current routing precedence is:
1. conversation override
2. campaign-specific handling
3. stage-based handling
4. default handling

### Memory

Nazar already has per-contact memory in the backend.

Current state:
- memory is functional
- DB-backed fallback is working
- Chroma/vector path is not the final production-grade setup yet

So memory is real and useful, but the architecture is still transitional.

## Channel Support

### WhatsApp

WhatsApp is integrated in the backend and product setup flow.

What exists:
- send path
- inbound webhook path
- diagnostics screen in settings
- token / phone number / webhook config support

What is still difficult:
- Meta sandbox restrictions
- recipient allowlists in test mode
- the lack of a dedicated business number during development

### Telegram

Telegram was added as a practical testing transport.

What exists:
- inbound Telegram messages create contacts and conversations
- manual replies can be sent back through Telegram
- bot replies can go out through Telegram
- campaigns can target Telegram contacts

Telegram is being used as a real transport for testing product behavior while WhatsApp remains commercially important for the final product.

## Main User Flows Built So Far

### Flow 1: Inbound lead

1. A person messages Nazar through a connected channel
2. Nazar creates or finds the contact
3. Nazar creates or updates the conversation
4. AI classifies the message
5. Stage and score can update
6. Nazar decides whether AI or a human should handle the thread
7. The conversation appears in the inbox

### Flow 2: Campaign outbound

1. A rep creates a campaign
2. They name it
3. They choose audience by stage and/or group
4. They choose template or custom copy
5. They choose reply handling
6. Nazar launches the campaign
7. Replies come back into Conversations
8. Those replies update the contact, pipeline, and inbox state

### Flow 3: Human-assisted selling

1. AI determines the thread should be handled by a human or reviewed by a human
2. Nazar assigns or queues the conversation
3. AI may prepare a draft
4. The rep reviews, edits, and sends
5. The contact continues moving through the funnel

### Flow 4: Contact and group management

1. A contact is added manually or via channel
2. The contact can be assigned to a group
3. Groups can later be used for filtering and campaign targeting
4. This works independently of source channel

## Product Decisions Already Made

These are important because the implementation already follows them.

### Campaign handling is per campaign

Reply behavior for a campaign is not primarily global.

That means:
- win-back campaigns can behave one way
- proposal push campaigns can behave another way

### Contacts are the core record

Nazar is not just a bot or inbox.

Contacts are the base commercial object that:
- campaigns operate on
- conversations attach to
- the pipeline tracks
- insights evaluate

### AI setup should not dominate the product

The app is being restructured so that operators mainly use:
- Campaigns
- Contacts
- Pipelines
- Conversations
- Insights
- Analytics

And not raw AI configuration screens.

### UI must reflect real functionality

The product is being developed under the rule:
- no purely decorative workflow UI
- no backend wording exposed as if it were operator-facing product language
- if a control exists, it should do real work

## What Is Working Well

Current strengths:
- conversation routing is increasingly aligned
- campaigns are now materially useful
- Telegram provides real transport testing
- contact, conversation, and pipeline models are coherent
- live UI updates now work without page refresh
- the product IA is much closer to a sellable structure than earlier builds

## What Is Still Transitional

These areas exist, but are not yet final-grade.

### 1. Memory architecture

Memory works, but the long-term production setup should be stronger than the current fallback path.

### 2. Insights depth

Insights exist, but the “AI helps close deals” layer still needs to become much stronger.

Examples still needed:
- richer objection summaries
- better next-best-action quality
- clearer deal risk framing

### 3. Campaign sophistication

Campaigns are functional, but not yet complete.

Still needed later:
- richer segmentation
- saved segment management
- drip sequences
- stronger campaign analytics

### 4. Team operations

The base team layer exists, but team-scale operational depth still needs work.

Still needed later:
- stronger workload visibility
- SLA/aging views
- manager operating views

## Current Engineering Direction

The product is no longer being built as a generic CRM dashboard.

It is now being pushed toward:
- a sales campaign engine
- an AI qualification engine
- a deal-closing assistant

The current build priorities are:
1. campaign operations
2. insights that help close deals
3. team operating layer
4. channel setup/onboarding reliability

## Practical Notes

### Local app

Current local preview has been running on:
- `http://localhost:8002`

### Branch

Primary working branch:
- `codex/product-foundation`

### Transport reality

WhatsApp is still the target commercial channel.

Telegram exists mainly so the product can be exercised end to end without waiting on Meta restrictions or a dedicated WhatsApp number.

## Summary

Nazar already has a working foundation for:
- contacts
- campaigns
- conversations
- pipeline movement
- AI classification
- AI replies
- AI-assisted human workflows
- live updates
- notifications
- multi-channel testing

The product is no longer at the “idea demo” stage.

It is at the stage where the main work is:
- tightening usability
- making the operating layer stronger
- improving commercial readiness
- deepening the AI value on top of the existing workflow engine
