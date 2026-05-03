# Demo Reset — One-Click Cheat Sheet

Use this **before every prospect demo** to guarantee a clean, impressive
state. Pick whichever option fits your situation.

---

## TL;DR

The fastest path:

```bash
cd nazar
./reset_demo.sh           # one command, ~15 seconds
```

That wipes the demo dataset and reseeds it with the Bloom Interiors
storyline — 12 contacts across all 6 pipeline stages, ₹77L+ pipeline,
5 KB documents, 7 templates, 4 campaigns, and 31 days of analytics.

---

## All the ways to reset

### 1. From your laptop terminal (recommended for local demos)

```bash
./reset_demo.sh
```

What it does:
1. Runs `seed_demo.py` → wipes & reseeds the database.
2. If the server is running, runs `demo_polish.py` → adds a few
   AI-generated WhatsApp conversations so the inbox isn't empty when
   you open it.

Idempotent — safe to run repeatedly.

### 2. From a remote machine (when the server runs elsewhere)

If your server runs in Docker, on a VPS, or anywhere you don't have a
terminal:

```bash
./reset_demo.sh --remote
```

This calls `POST /api/admin/reset-demo` over HTTP, which executes the
same scripts inside the server's runtime.

You can also call the endpoint directly with `curl`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@nazar.app","password":"changeme123"}' \
  | jq -r .token)

curl -X POST http://localhost:8001/api/admin/reset-demo \
  -H "Authorization: Bearer $TOKEN"
```

Returns `{"ok": true, "log": "…"}` after ~15s.

### 3. Bookmarklet (zero-terminal demos)

Paste this once into your browser bookmarks — clicking it after login
triggers a reset without leaving the dashboard:

```js
javascript:(async()=>{const t=localStorage.getItem('nazar.session.token');
if(!t){alert('Not logged in.');return;}
if(!confirm('Reset demo state? This wipes contacts/conversations/KB.'))return;
const r=await fetch('/api/admin/reset-demo',{method:'POST',
headers:{'Authorization':'Bearer '+t}}).then(r=>r.json());
alert(r.ok?'✓ Demo reset. Refresh the page.':'✗ Failed: '+JSON.stringify(r));
location.reload();})();
```

---

## Safety controls

The `/api/admin/reset-demo` endpoint:

- Requires a valid auth token (session or API key).
- Refuses to run unless `NAZAR_DEMO_MODE=1` is set in `.env`.
  (Production should keep this `0`.)
- Holds a process-wide lock — only one reset can run at a time.
- Times out after 180 seconds per step (so a stuck script can't hang
  the server).

---

## What "clean state" actually means

After a reset, you can promise the prospect every screen will show:

| Screen        | Content |
|---------------|---------|
| Overview      | ₹77L pipeline, ₹24L revenue, 9 active leads |
| Pipeline      | All 6 stages populated (New → Won + Lost) |
| Inbox         | 12 conversations with backdated AI history |
| KB            | 5 Bloom Interiors documents, ChromaDB-indexed |
| Templates     | 7 WhatsApp templates with realistic usage stats |
| Campaigns     | 4 campaigns (1 scheduled, 1 active, 2 completed) |
| Analytics     | 31 days of message/AI/handoff/lead trend data |

A pytest smoke test (`tests/test_demo_state.py`) verifies all of the
above. Run it any time to confirm:

```bash
.venv/bin/python -m pytest tests/test_demo_state.py -v
```

---

## Recovering when something looks wrong

| Symptom | Fix |
|---------|-----|
| Inbox empty even after reset | Run `./reset_demo.sh` again — `demo_polish.py` only runs if the server was up. |
| 'New' stage missing leads | Don't manually message Akhil/Nupur from the dashboard before the demo — that auto-promotes them. Reset to fix. |
| KB returns "no results" | ChromaDB collection corrupted — `rm -rf data/.chroma_health data/kb && ./reset_demo.sh`. |
| Tour button covering Send | Already fixed — the tour launcher hides itself on `/inbox/:id`. |
