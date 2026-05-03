"""
demo_polish.py — One-shot script to polish the Nazar demo state.

Run this AFTER seed_demo.py and the server is running.
It:
  1. Dedupes Knowledge Base documents (keeps newest of each title).
  2. Pushes a clean Nazar-focused Quick-Edit KB content.
  3. Pre-runs a few /api/simulate calls so the inbox shows real
     AI-generated conversations on opening (no empty state).
  4. Verifies each demo path returns 200.

Usage:
    cd /home/workspace/Nazar/nazar
    .venv/bin/python demo_polish.py
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://localhost:8001"
EMAIL = "admin@nazar.app"
PASSWORD = "changeme123"


def http(method: str, path: str, *, token: str | None = None, body: dict | None = None,
         timeout: int = 60) -> tuple[int, dict | str]:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def login() -> str:
    code, data = http("POST", "/api/auth/login",
                      body={"email": EMAIL, "password": PASSWORD})
    if code != 200 or not isinstance(data, dict) or not data.get("token"):
        raise SystemExit(f"Login failed: {code} {data}")
    return data["token"]


def dedupe_kb(token: str) -> None:
    print("\n── Step 1: Dedupe Knowledge Base ──")
    code, data = http("GET", "/api/kb/documents", token=token)
    if code != 200:
        print(f"  ⚠️  Could not list KB documents ({code}); skipping dedupe.")
        return
    docs = data.get("documents", []) if isinstance(data, dict) else []
    print(f"  Found {len(docs)} documents.")
    by_title: dict[str, list[dict]] = {}
    for d in docs:
        by_title.setdefault(d.get("title", ""), []).append(d)

    deleted = 0
    for title, group in by_title.items():
        if len(group) <= 1:
            continue
        # Keep the document with the highest chunk_count, else first
        group.sort(key=lambda d: (d.get("chunk_count", 0), d.get("created_at", "")),
                   reverse=True)
        keep = group[0]
        for dup in group[1:]:
            doc_id = dup.get("id")
            if not doc_id:
                continue
            c, _ = http("DELETE", f"/api/kb/documents/{doc_id}", token=token)
            if c in (200, 204):
                deleted += 1
            else:
                print(f"    ! could not delete {title} ({doc_id}): {c}")
        print(f"  • {title}: kept 1, removed {len(group)-1}")
    print(f"  Deleted {deleted} duplicate documents.")


def push_quick_edit(token: str) -> None:
    print("\n── Step 2: Refresh Quick-Edit KB content ──")
    kb_path = Path(__file__).parent / "data" / "knowledge_base.txt"
    content = kb_path.read_text(encoding="utf-8")
    code, data = http("POST", "/api/kb/upload", token=token, body={"content": content})
    if 200 <= code < 300:
        print(f"  ✓ Quick-Edit content refreshed ({len(content)} chars).")
    else:
        print(f"  ✗ Quick-Edit refresh failed: {code} {str(data)[:200]}")


# Demo conversations to pre-seed. Targeted by *contact name* (not index)
# so we can guarantee they don't hit the freshly-seeded "New" leads —
# auto-classification would otherwise promote them out of the New column
# and leave the pipeline funnel looking lopsided in the demo.
#
# These names match contacts seeded in seed_demo.py. The chats are
# Bloom-Interiors-themed, so the AI's grounded reply will reference
# pricing / process / FAQs from the seeded knowledge base.
DEMO_CHATS = [
    ("Tanvi Agarwal", [
        "Hi! I'm planning a 3BHK renovation in Whitefield — can you share approximate pricing?",
        "What's your timeline for a full-home interior?",
    ]),
    ("Vivek & Sneha Rao", [
        "Do you offer modular kitchens with German hardware? Any current offers?",
    ]),
    ("Reema Desai", [
        "Can I book a site visit this weekend? Also, do you handle vastu requirements?",
    ]),
    ("Sandeep & Priya Kulkarni", [
        "We loved your Diwali kitchen post. What's the price range for a 10x12 modular kitchen?",
    ]),
]

# Stages we MUST NEVER pre-seed chats into, because doing so will trigger
# pipeline auto-classification and break the funnel demo.
PROTECTED_STAGES = {"New", "Lost"}


def seed_simulated_chats(token: str) -> None:
    print("\n── Step 3: Pre-seed simulated AI conversations ──")
    code, data = http("GET", "/api/contacts", token=token)
    contacts = data.get("contacts", []) if isinstance(data, dict) else []
    if len(contacts) < 4:
        print(f"  ⚠️  Only {len(contacts)} contacts; need at least 4. Run seed_demo.py first.")
        return

    by_name = {c.get("name", ""): c for c in contacts}

    for name, msgs in DEMO_CHATS:
        contact = by_name.get(name)
        if not contact:
            print(f"  ⚠️  Skipping '{name}' (not in seeded contacts).")
            continue

        stage = contact.get("pipeline_stage", "")
        if stage in PROTECTED_STAGES:
            print(f"  ⚠️  Skipping '{name}' — stage '{stage}' is protected from auto-promotion.")
            continue

        cid = contact.get("contact_id")
        print(f"  → {name} [{stage}] ({cid})")
        for m in msgs:
            code, resp = http("POST", "/api/simulate/message", token=token,
                              body={"contact_id": cid, "message": m}, timeout=90)
            if code == 200 and isinstance(resp, dict):
                reply = (resp.get("reply") or "")[:80].replace("\n", " ")
                print(f"     « {m[:60]}")
                print(f"     » {reply}…")
            else:
                print(f"     ✗ {code} {str(resp)[:120]}")
            time.sleep(0.5)


def verify(token: str) -> None:
    print("\n── Step 4: Verify demo endpoints ──")
    checks = [
        ("Overview",            "GET",  "/api/overview"),
        ("Contacts",            "GET",  "/api/contacts"),
        ("Conversations",      "GET",  "/api/conversations"),
        ("Templates",           "GET",  "/api/templates"),
        ("KB documents",        "GET",  "/api/kb/documents"),
        ("KB content",          "GET",  "/api/kb"),
        ("Campaigns",           "GET",  "/api/campaigns"),
        ("Setup status",        "GET",  "/api/setup/status"),
        ("Handoffs",            "GET",  "/api/handoffs"),
        ("Followups",           "GET",  "/api/followups"),
    ]
    for label, method, path in checks:
        code, _ = http(method, path, token=token, timeout=10)
        flag = "✓" if 200 <= code < 300 else "✗"
        print(f"  {flag}  {label:<22} {method} {path}  → {code}")


def main():
    print("Polishing Nazar demo state…")
    token = login()
    print(f"  ✓ Logged in.")
    dedupe_kb(token)
    push_quick_edit(token)
    seed_simulated_chats(token)
    verify(token)
    print("\n✅  Demo polish complete.\n"
          "   • Login: admin@nazar.app / changeme123\n"
          "   • Open: http://localhost:8001\n")


if __name__ == "__main__":
    main()
