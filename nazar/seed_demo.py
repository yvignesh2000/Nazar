"""
Nazar — Bloom Interiors Demo Seed
=================================

Single, idempotent script that builds a complete, insight-rich demo around a
fictional but realistic business: **Bloom Interiors**, a Bangalore-based
interior design studio that handles 80+ daily WhatsApp leads for home
renovations, modular kitchens, and full-home interiors.

What this script does (in order):

    1. WIPE — removes ghost contacts (no messages, or test rows) and clears
       the kb_documents and campaigns tables (per-workspace).
    2. CONTACTS + CONVERSATIONS — seeds 12 realistic Bloom Interiors customers
       across the 6 pipeline stages, with backdated message histories.
    3. KNOWLEDGE BASE — seeds 5 documents about Bloom Interiors (services,
       pricing, process, FAQs, testimonials) into the SQLite `kb_documents`
       table AND ChromaDB so the live AI grounds its replies in this content.
    4. TEMPLATES — seeds 7 WhatsApp templates with realistic usage stats.
    5. CAMPAIGNS — seeds 4 campaigns (1 scheduled, 1 active, 2 completed)
       directly into the campaigns SQLite table.
    6. ANALYTICS EVENTS — seeds 30 days of message/AI/handoff/lead events
       into per-day jsonl files, weighted by hour-of-day so the trend chart
       looks like a real business.

Run:
    python3 seed_demo.py            # full reset + reseed
    python3 seed_demo.py --keep     # don't wipe; only add missing items

Idempotency: re-running with --keep is safe.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ChromaDB compatibility shim — must be before any chromadb import.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "core"))

from contact_manager import (  # noqa: E402
    create_contact, update_contact, move_stage, update_lead_score,
    save_message, list_contacts, get_contact_by_phone, delete_contact,
    normalize_phone, DEFAULT_WORKSPACE,
)
from database import get_db  # noqa: E402

logging.getLogger("nazar").setLevel(logging.WARNING)

IST = timezone(timedelta(hours=5, minutes=30))
DATA = ROOT / "data"
WORKSPACE = DEFAULT_WORKSPACE


# ============================================================================
# Helpers
# ============================================================================

def now_iso(days_ago: int = 0, hours_ago: int = 0, minutes_ago: int = 0) -> str:
    return (
        datetime.now(IST)
        - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
    ).isoformat()


def banner(title: str) -> None:
    line = "─" * 60
    print(f"\n{line}\n  {title}\n{line}")


# ============================================================================
# 1. WIPE — remove ghost rows and reset KB / campaigns
# ============================================================================

def wipe_all_contacts(verbose: bool = True) -> None:
    """
    Remove every contact in the default workspace so we can rebuild a coherent
    Bloom Interiors customer base from scratch. Cascades to messages,
    handoff_states, ai_drafts, etc. via the contact's own ID.
    """
    contacts = list_contacts(workspace_id=WORKSPACE)
    if verbose:
        print(f"  removing {len(contacts)} existing contacts...")

    deleted = 0
    for c in contacts:
        cid = c["contact_id"]
        try:
            delete_contact(cid)
            deleted += 1
        except Exception as e:
            print(f"  ! failed to remove {c.get('name')}: {e}")

    # Also force-delete any orphaned rows whose contact_id no longer maps to a
    # valid contact, so the dashboard never shows ghost messages.
    with get_db() as conn:
        for table, key in (
            ("messages",       "contact_id"),
            ("handoff_states", "contact_id"),
            ("handoff_events", "contact_id"),
            ("ai_drafts",      "contact_id"),
            ("reply_modes",    "contact_id"),
            ("assignments",    "contact_id"),
        ):
            try:
                conn.execute(
                    f"DELETE FROM {table} WHERE {key} NOT IN (SELECT id FROM contacts)"
                )
            except Exception:
                pass

    print(f"  → {deleted} contacts removed (workspace clean)")


def wipe_kb_and_campaigns() -> None:
    """Clear KB docs (JSON + Chroma + SQLite) and campaigns for a clean reseed."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM kb_documents WHERE workspace_id = ?", (WORKSPACE,)
        )
        kb_n = cur.rowcount
        cur = conn.execute(
            "DELETE FROM campaigns WHERE workspace_id = ?", (WORKSPACE,)
        )
        cmp_n = cur.rowcount
    print(f"  → {kb_n} KB rows (sqlite) and {cmp_n} campaigns cleared")

    # KB metadata is stored in data/kb/docs.json — clear it
    kb_dir = DATA / "kb"
    if kb_dir.exists():
        docs_json = kb_dir / "docs.json"
        if docs_json.exists():
            docs_json.write_text("{}")
            print("  → kb/docs.json cleared")
        # Also clear raw text fallbacks from older seedings
        raw_dir = kb_dir / "raw"
        if raw_dir.exists():
            removed = 0
            for f in raw_dir.glob("*"):
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
            if removed:
                print(f"  → kb/raw/* cleared ({removed} files)")

    # Wipe ChromaDB collections too, so old KB doesn't shadow new content
    try:
        from knowledge_base import _get_chroma  # type: ignore
        client = _get_chroma()
        if client:
            for col in client.list_collections():
                try:
                    client.delete_collection(col.name)
                except Exception:
                    pass
            print("  → ChromaDB collections cleared")
    except Exception:
        pass

    # Wipe analytics per-day files (we'll reseed)
    analytics_dir = DATA / "analytics"
    if analytics_dir.exists():
        removed = 0
        for f in analytics_dir.glob("*.jsonl*"):
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
        if removed:
            print(f"  → {removed} analytics files cleared")

    # Wipe templates so they get re-seeded with correct usage stats
    tpls_path = DATA / "templates.json"
    if tpls_path.exists():
        try:
            tpls_path.unlink()
            print("  → templates.json cleared")
        except Exception:
            pass


# ============================================================================
# 2. CONTACTS + CONVERSATIONS — Bloom Interiors customer base
# ============================================================================
#
# Pipeline distribution (12 contacts → realistic funnel):
#   New        ×2   (just enquired, AI handling)
#   Qualified  ×3   (asked for quote, sent budget range)
#   Proposal   ×3   (3D mockups / quote sent)
#   Negotiation×1   (price discussion in progress)
#   Won        ×2   (project signed, work in progress)
#   Lost       ×1   (chose competitor)

CONTACTS: list[dict] = [
    # ----- WON -----
    {
        "name": "Aishwarya & Karthik Iyer",
        "phone": "+919845001122",
        "company": "Sobha Dream Acres, Tower 7",
        "source": "Instagram",
        "stage": "Won",
        "deal_value": 1850000,
        "lead_score": 95,
        "tags": ["full-home", "premium", "happy-customer"],
        "assigned_to": "owner",
        "notes": "3BHK full-home. Signed ₹18.5L contract on 12 Apr. Project in progress — modular kitchen done, civil work next. Loves the live updates feature.",
        "last_contacted_days_ago": 1,
        "conversations": [
            (24, [
                ("inbound", "Hi Bloom! Saw your 3BHK reel on Instagram — the navy + brass kitchen. We just got possession at Sobha Dream Acres T7, can you do similar?", "contact"),
                ("outbound", "Hi Aishwarya! Thanks for reaching out. That kitchen is one of our favourites too. Sobha Dream Acres is a beautiful property — we've done 4 homes there in the last 8 months. Are you looking at modular kitchen alone, or full-home interiors?", "bot"),
                ("inbound", "Full home please. 3BHK, 1450 sqft. We move in around June. Budget around 18-20L if possible.", "contact"),
                ("outbound", "Perfect window — June gives us 8 weeks which is comfortable for full-home. At 1450 sqft and ₹18-20L you'll get our Premium package: full modular kitchen, 3 wardrobes, TV unit, foyer console, dining unit, false ceiling and lighting design. Want me to schedule a free site visit and 3D consultation?", "bot"),
            ]),
            (22, [
                ("inbound", "Yes please. We're free Saturday after 11.", "contact"),
                ("outbound", "Booked. Mahesh (our senior designer) will be there Saturday 11:30. He'll bring our material library and 2 reference projects in your tower. ✓", "bot"),
            ]),
            (18, [
                ("outbound", "Hi Aishwarya, Mahesh here. Sharing the 3D walkthrough we built from yesterday's site visit. Two kitchen options — please review and let me know which direction you like. Floor plan PDF coming next.", "human"),
                ("inbound", "Wow, the matte navy with the brass ledge is stunning. Going with Option A. Karthik agrees.", "contact"),
            ]),
            (16, [
                ("outbound", "Locked. Final BOQ: ₹18,42,000 incl. GST. Payment in 4 milestones (30/30/30/10). Contract attached. Once signed, we start material procurement.", "human"),
                ("inbound", "Signed and forwarded. Token payment done — ref TXN8847123.", "contact"),
                ("outbound", "Received. Procurement starts Monday. You'll get weekly progress photos every Friday — automated via WhatsApp 📸", "human"),
            ]),
            (8, [
                ("outbound", "Week 1 update: Carcass cutting done at our Hoskote unit. Site team prepping civil scope at the apartment. Photos attached.", "bot"),
                ("inbound", "Looks great! Quick question — can we add LED strip under the breakfast counter? My mom mentioned it.", "contact"),
                ("outbound", "Absolutely. Cool white LED strip with diffuser, ~₹4,800 add-on. I'll add to the change-order log and confirm before installation.", "human"),
            ]),
            (1, [
                ("outbound", "Week 3 update: Modular kitchen 90% installed. Brass ledge arrived from Jaipur — looks even better in person. Civil work for false ceiling starts Wednesday. Site walkthrough Saturday if you'd like to drop by.", "bot"),
                ("inbound", "Yes! See you Saturday 4pm. Also — referring my colleague Pranav, he's doing his 2BHK in Whitefield. Sending his number now.", "contact"),
                ("outbound", "Thank you so much, Aishwarya 🙏 We'll reach out to Pranav this week. Your referral credit (₹15,000 off the final invoice) is locked in.", "human"),
            ]),
        ],
    },
    {
        "name": "Rohit Bhandari",
        "phone": "+919845001133",
        "company": "Prestige Lakeside Habitat",
        "source": "Referral",
        "stage": "Won",
        "deal_value": 580000,
        "lead_score": 88,
        "tags": ["modular-kitchen", "wardrobe", "annual"],
        "assigned_to": "owner",
        "notes": "Modular kitchen + 2 wardrobes. Signed ₹5.8L. Repeat customer (did his Adarsh apartment 2 years ago). Always pays on time.",
        "last_contacted_days_ago": 5,
        "conversations": [
            (35, [
                ("inbound", "Hi Bloom team — Rohit here, you did my Adarsh apartment kitchen 2 years ago. Just bought a 2BHK at Prestige Lakeside, want you to do the kitchen + 2 wardrobes again.", "contact"),
                ("outbound", "Rohit! Welcome back 🙌 Of course. Same Mahesh handling? Send me the floor plan when free, we'll quote within 48 hrs.", "human"),
                ("inbound", "Floor plan attached. Possession next month. Same finish as before if possible (the matte white + walnut combo).", "contact"),
            ]),
            (33, [
                ("outbound", "Quote ready: Modular kitchen ₹3.2L (L-shape, soft-close, granite top) + 2 wardrobes (M.Bedroom 8ft, Kid's 6ft) ₹2.4L + installation ₹0.2L. Total ₹5.8L incl. GST. Same finish locked. PDF attached.", "human"),
                ("inbound", "Approved. Send the contract.", "contact"),
            ]),
            (30, [
                ("outbound", "Contract signed and token received. Production starts this week — delivery in 5 weeks as agreed.", "human"),
            ]),
            (12, [
                ("outbound", "Update: Kitchen carcass + shutters ready. Wardrobes 80% done. Installation date: 18 April. ✓", "bot"),
            ]),
            (5, [
                ("outbound", "Installation complete! How's everything looking? Any touch-ups needed?", "human"),
                ("inbound", "All perfect, as expected. Final payment processed. Already told 2 friends about you.", "contact"),
                ("outbound", "Thank you Rohit, that means a lot 🙏 Sending you the warranty card and care guide. Always here if you need anything down the line.", "human"),
            ]),
        ],
    },

    # ----- NEGOTIATION -----
    {
        "name": "Pranav Shetty",
        "phone": "+919845001144",
        "company": "Brigade Cornerstone Utopia, Whitefield",
        "source": "Referral",
        "stage": "Negotiation",
        "deal_value": 720000,
        "lead_score": 82,
        "tags": ["referral", "2bhk", "negotiating"],
        "assigned_to": "owner",
        "notes": "Referred by Aishwarya Iyer. 2BHK kitchen + 2 wardrobes + TV unit. Quote sent ₹7.2L, asking for ₹6.5L. Decision expected this week.",
        "last_contacted_days_ago": 0,
        # Bot is paused — sales rep is actively negotiating price.
        "bot_paused": "Price negotiation in progress — owner handling personally",
        "conversations": [
            (10, [
                ("inbound", "Hi, Aishwarya from Sobha Dream Acres referred you. Looking at kitchen + 2 wardrobes + TV unit for my 2BHK at Brigade Cornerstone. Possession in 6 weeks.", "contact"),
                ("outbound", "Hi Pranav! Thanks to Aishwarya for the kind word. We'd love to work on your home. 6 weeks is comfortable for that scope. Can you share the floor plan? We'll set up a free 3D consultation.", "bot"),
                ("inbound", "Floor plan attached. Mostly looking at neutral palette — beige, off-white, light wood.", "contact"),
            ]),
            (7, [
                ("outbound", "Pranav, sharing the 3D walkthrough Mahesh built. Modular kitchen with breakfast counter, 8ft master wardrobe, 6ft guest wardrobe, full-wall TV unit with floating shelves. Total quote: ₹7,20,000 incl. GST. Detailed BOQ in the PDF.", "human"),
                ("inbound", "Loved the design. But 7.2L is a bit above my budget — I was hoping for around 6.5L. Can we work something out?", "contact"),
            ]),
            (3, [
                ("outbound", "Pranav, I checked with the team. We can come to ₹6.85L if we move the TV unit to standard veneer instead of fluted (₹35K saving). Same finish for the kitchen and wardrobes — those are non-negotiable for the warranty. Fair?", "human"),
                ("inbound", "Hmm. Let me sleep on it. Can you do 6.5L flat if we sign this week?", "contact"),
            ]),
            (0, [
                ("inbound", "Sorry, just wanted to follow up. My wife is pushing to decide today.", "contact"),
                ("outbound", "Hey Pranav, totally understand. Let me check with the principal designer one more time — will message you in the next 30 min with our final number. 🙏", "human"),
            ]),
        ],
    },

    # ----- PROPOSAL -----
    {
        "name": "Dr. Megha Suresh",
        "phone": "+919845001155",
        "company": "Embassy Boulevard Villa",
        "source": "Google",
        "stage": "Proposal",
        "deal_value": 3400000,
        "lead_score": 90,
        "tags": ["villa", "premium", "high-value"],
        "assigned_to": "owner",
        "notes": "4BHK villa, 3200 sqft. Premium full-home with imported finishes. Quote ₹34L sent yesterday. Decision in 2 weeks per her timeline.",
        "last_contacted_days_ago": 1,
        "conversations": [
            (14, [
                ("inbound", "Hello, found you on Google. Looking for full-home interiors for a 4BHK villa at Embassy Boulevard. We want a contemporary look with some Indian touches.", "contact"),
                ("outbound", "Hi Dr. Megha, thank you for reaching out. Embassy Boulevard villas are stunning — we've done 2 homes in the same community. Could you share the layout and any reference images you like? We'll put together a tailored proposal.", "bot"),
            ]),
            (11, [
                ("inbound", "Layout attached. References: I love this Mumbai apartment from your portfolio — the brass + travertine combo. My husband wants a dedicated bar and a study.", "contact"),
                ("outbound", "Excellent taste 🙂 Both bar and study are very doable. We typically use Italian travertine veneer (lighter than slab) for cost-effectiveness. Can we schedule a site visit + design consultation for this Saturday or Sunday?", "human"),
            ]),
            (4, [
                ("outbound", "Dr. Megha — sharing the 3D walkthrough from last weekend. Highlights: Travertine + brass kitchen, statement bar with backlit shelves in the foyer, study with built-in shelving and reading nook. Full BOQ attached. Quote: ₹34,20,000 incl. GST + ₹2L imported lights buffer.", "human"),
            ]),
            (1, [
                ("inbound", "The design is beautiful, thank you. Need 2 weeks to discuss with my husband and look at one more vendor for comparison. Will revert by 30th.", "contact"),
                ("outbound", "Of course, Dr. Megha — take your time. To help with the comparison, here's a one-page summary of what's included, our 5-year warranty, and the timeline. Happy to answer any specific questions in the meantime.", "human"),
            ]),
        ],
    },
    {
        "name": "Vivek & Sneha Rao",
        "phone": "+919845001166",
        "company": "Salarpuria Sattva Magnus",
        "source": "WhatsApp",
        "stage": "Proposal",
        "deal_value": 1240000,
        "lead_score": 78,
        "tags": ["full-home", "3bhk"],
        "assigned_to": "owner",
        "notes": "3BHK full-home interiors. Quote ₹12.4L sent. Sneha is the decision maker. Comparing with 1 other vendor.",
        "last_contacted_days_ago": 2,
        "conversations": [
            (12, [
                ("inbound", "Hi! We're Vivek & Sneha. Just got our 3BHK at Salarpuria Sattva Magnus. Need full-home interiors, possession in 7 weeks.", "contact"),
                ("outbound", "Welcome! 7 weeks is workable. Could you share the floor plan and a rough budget range so we can scope correctly?", "bot"),
                ("inbound", "Floor plan attached. Budget around 12-13L. We like minimal Scandinavian style — light woods, lots of white, no clutter.", "contact"),
            ]),
            (9, [
                ("outbound", "Perfect aesthetic — we love that brief. Booking a free site visit + 3D consultation. Saturday 10am works?", "bot"),
                ("inbound", "Yes, see you then.", "contact"),
            ]),
            (5, [
                ("outbound", "Sharing the Scandi-inspired 3D walkthrough. Light oak, white matte cabinets, subtle textures. Full BOQ: ₹12,40,000 incl. GST. PDF attached.", "human"),
            ]),
            (2, [
                ("inbound", "We love it! Comparing with one other vendor for due diligence. Will get back by Friday.", "contact"),
                ("outbound", "Take all the time you need. If it helps, here's our 5-year warranty doc and 3 customer references from the same community 👇", "human"),
            ]),
        ],
    },
    {
        "name": "Captain Anand Rao",
        "phone": "+919845001177",
        "company": "Adarsh Palm Retreat",
        "source": "Google",
        "stage": "Proposal",
        "deal_value": 460000,
        "lead_score": 70,
        "tags": ["modular-kitchen", "senior-citizen-friendly"],
        "assigned_to": "owner",
        "notes": "Retired naval officer. Modular kitchen + 1 wardrobe. Specifically asked for senior-citizen-friendly heights. Quote ₹4.6L sent.",
        "last_contacted_days_ago": 3,
        # Bot paused — owner wants to handle senior-citizen accessibility brief personally.
        "bot_paused": "Senior-citizen brief — owner handling personally",
        "conversations": [
            (8, [
                ("inbound", "Good evening. I'm a retired naval officer, looking for a modular kitchen and one wardrobe. The home is for myself and my wife — both senior citizens. Need heights and handles suitable for our age.", "contact"),
                ("outbound", "Good evening Captain Rao, thank you for reaching out. We're very experienced with senior-friendly design — pull-down shelves, comfortable counter heights, easy-grip handles, anti-slip flooring inserts. Could you share your floor plan?", "bot"),
                ("inbound", "Plan attached. Adarsh Palm Retreat, 2BHK.", "contact"),
            ]),
            (5, [
                ("outbound", "Captain — proposal attached. Modular kitchen with 850mm counter (vs standard 900mm), pull-down shelves on upper cabinets, soft-close everything, easy-grip cup handles. Wardrobe with mid-height hanging rod (no high shelves). Total ₹4,60,000 incl. GST.", "human"),
            ]),
            (3, [
                ("inbound", "Thank you. Discussing with my wife and son. Will revert this week.", "contact"),
                ("outbound", "Of course, Captain. Take your time. If your son would like to visit any of our completed senior-friendly projects (we have 2 in Adarsh community itself), happy to arrange.", "human"),
            ]),
        ],
    },

    # ----- QUALIFIED -----
    {
        "name": "Tanvi Agarwal",
        "phone": "+919845001188",
        "company": "Godrej Reflections",
        "source": "Instagram",
        "stage": "Qualified",
        "deal_value": 950000,
        "lead_score": 65,
        "tags": ["full-home", "2bhk"],
        "assigned_to": "owner",
        "notes": "2BHK full-home. Site visit booked Saturday. Budget 9-10L. Wedding gift from parents.",
        "last_contacted_days_ago": 1,
        "conversations": [
            (5, [
                ("inbound", "Hi! Saw your reel today. Getting married next month and parents are gifting us a 2BHK at Godrej Reflections. Need full-home interiors. We move in around July.", "contact"),
                ("outbound", "Congratulations Tanvi 🥳 We'd be honoured to work on your first home. July gives us comfortable runway. What's your style direction — minimal, classic, eclectic, traditional? And rough budget?", "bot"),
                ("inbound", "Modern eclectic — some colour, brass accents, lots of plants. Budget 9-10L.", "contact"),
            ]),
            (1, [
                ("outbound", "Great brief — that's a really fun direction. Booking your free site visit + 3D consultation for Saturday 11am. Mahesh will get in touch to confirm.", "bot"),
                ("inbound", "Perfect, see you then!", "contact"),
                ("outbound", "Confirmed for Saturday 11am 🌿 Mahesh will share his number shortly so you can reach him directly. Looking forward to it!", "bot"),
            ]),
        ],
    },
    {
        "name": "Sandeep & Priya Kulkarni",
        "phone": "+919845001199",
        "company": "Mantri Webcity",
        "source": "Walk-in",
        "stage": "Qualified",
        "deal_value": 280000,
        "lead_score": 55,
        "tags": ["modular-kitchen"],
        "assigned_to": "owner",
        "notes": "Walk-in to studio. Modular kitchen only. Existing apartment, retrofit job. Budget 2.5-3L.",
        "last_contacted_days_ago": 2,
        "conversations": [
            (4, [
                ("inbound", "Hi, we visited your studio in Indiranagar yesterday. Looking for just a modular kitchen retrofit at Mantri Webcity. Existing kitchen has to come out. Budget around 2.5-3L.", "contact"),
                ("outbound", "Hi Sandeep, thanks for visiting! Retrofits are very doable — we usually finish in 7-10 days site time. Could you share photos of your current kitchen + measurements (or floor plan)? We'll send a tailored quote.", "bot"),
                ("inbound", "Photos and rough measurements attached. It's an L-shape, ~7ft x 6ft.", "contact"),
            ]),
            (2, [
                ("outbound", "Got it. Standard L-shape modular at this size lands around ₹2.6-2.9L depending on shutter finish. Sending detailed quote tomorrow with 2 finish options. Cool?", "bot"),
                ("inbound", "Yes please.", "contact"),
                ("outbound", "Perfect — quote going out tomorrow morning by 10am. I'll include both finish options (matte laminate vs acrylic) so you can compare side by side.", "bot"),
            ]),
        ],
    },
    {
        "name": "Reema Desai",
        "phone": "+919845002211",
        "company": "Independent house, JP Nagar",
        "source": "Google",
        "stage": "Qualified",
        "deal_value": 650000,
        "lead_score": 60,
        "tags": ["wardrobes", "study", "kids-room"],
        "assigned_to": "owner",
        "notes": "Wardrobes for 3 bedrooms + kids' study unit. Independent house renovation. Quote due this week.",
        "last_contacted_days_ago": 1,
        "conversations": [
            (3, [
                ("inbound", "Hello, looking for wardrobes for 3 bedrooms in our independent house in JP Nagar. Also a study + storage combo for my kids' room.", "contact"),
                ("outbound", "Hi Reema! Sounds like a fun project — kids' rooms are our favourite. Could you share dimensions or photos of each space? We'll quote within 2 days.", "bot"),
                ("inbound", "Sending photos now. Master bedroom is 12x10, kids' is 11x10, guest is 10x9.", "contact"),
            ]),
            (1, [
                ("outbound", "Got everything. Working on the design + quote — will share by Wednesday 6pm. In the meantime, here are 5 of our recent kids' room projects for inspiration 👇", "bot"),
            ]),
        ],
    },

    # ----- NEW -----
    {
        "name": "Akhil Joseph",
        "phone": "+919845002233",
        "company": "Prestige Falcon City",
        "source": "Instagram",
        "stage": "New",
        "deal_value": 0,
        "lead_score": 25,
        "tags": ["new-lead"],
        "assigned_to": None,
        "notes": "",
        "last_contacted_days_ago": 0,
        "conversations": [
            (0, [
                ("inbound", "Hi, do you do modular kitchens for 2BHK?", "contact"),
                ("outbound", "Hi! Yes, modular kitchens are one of our specialties. For a typical 2BHK, our kitchens range from ₹2.5L to ₹4L depending on size, layout (L/U/parallel) and shutter finish. Could you share which property and rough timeline? Happy to set up a free consultation.", "bot"),
                ("inbound", "Prestige Falcon City. Possession next month.", "contact"),
                ("outbound", "Falcon City is great — we've done 3 kitchens there. Free site visit + 3D consultation can be booked this Saturday or Sunday. Would either work?", "bot"),
            ]),
        ],
    },
    {
        "name": "Nupur Banerjee",
        "phone": "+919845002244",
        "company": "Renting in Koramangala",
        "source": "WhatsApp",
        "stage": "New",
        "deal_value": 0,
        "lead_score": 15,
        "tags": ["new-lead", "rental"],
        "assigned_to": None,
        "notes": "",
        "last_contacted_days_ago": 0,
        "conversations": [
            (0, [
                ("inbound", "hi do you guys also do small things like just one bookshelf? im in a rented place", "contact"),
                ("outbound", "Hi Nupur! Yes — we do small custom pieces too (we call them micro-projects). For a single bookshelf, ballpark is ₹15K-40K depending on size, material and design. Could you share the wall dimensions or a photo of the space?", "bot"),
            ]),
        ],
    },

    # ----- LOST -----
    {
        "name": "Gaurav Malhotra",
        "phone": "+919845002255",
        "company": "Sobha Forest Edge",
        "source": "Google",
        "stage": "Lost",
        "deal_value": 0,
        "lead_score": 20,
        "tags": ["lost-price", "revisit-q3"],
        "assigned_to": None,
        "notes": "Wanted full-home at ₹8L for a 3BHK — well below our floor for that scope. Went with a low-cost vendor. Worth re-engaging in 6 months when he sees quality issues.",
        "last_contacted_days_ago": 18,
        "conversations": [
            (25, [
                ("inbound", "Hi, looking for full-home for 3BHK at Sobha Forest Edge. Budget 8L max.", "contact"),
                ("outbound", "Hi Gaurav, thanks for reaching out. To set expectations — for a 3BHK full-home with our material standards and 5-yr warranty, we typically start at ₹14L. We won't be able to meet the ₹8L target while keeping our quality bar. Would you consider a phased approach (kitchen + wardrobes first, rest later)?", "human"),
            ]),
            (20, [
                ("inbound", "No, we want everything done before move-in. Going with another vendor who's quoting 7.5L. Thanks anyway.", "contact"),
                ("outbound", "Completely understand, Gaurav. Wishing you a smooth move-in. If you want a second opinion on materials or contract terms before signing, happy to take a look (no charge). 🙂", "human"),
            ]),
            (18, [
                ("outbound", "Hi Gaurav — quick check-in. How did the project go? Just wanted to make sure all worked out well. We sometimes help fix issues for folks 6-12 months in if quality wasn't up to mark.", "bot"),
            ]),
        ],
    },
]


def seed_contacts() -> None:
    """Seed the Bloom Interiors customer base with backdated conversations."""
    existing_phones = {c["phone"] for c in list_contacts(workspace_id=WORKSPACE)}
    created = skipped = 0

    for data in CONTACTS:
        phone = normalize_phone(data["phone"])
        if phone in existing_phones:
            skipped += 1
            continue

        contact = create_contact(
            name=data["name"],
            phone=phone,
            company=data["company"],
            source=data["source"],
            assigned_to=data["assigned_to"],
            tags=data.get("tags", []),
            workspace_id=WORKSPACE,
        )
        cid = contact["contact_id"]

        if data["stage"] != "New":
            move_stage(cid, data["stage"])
        if data["deal_value"]:
            update_contact(cid, deal_value=float(data["deal_value"]))
        if data["lead_score"]:
            update_lead_score(cid, data["lead_score"])
        if data.get("notes"):
            update_contact(cid, notes=data["notes"])

        # Save messages (forward order); then BACKDATE timestamps directly
        # via SQL so the conversations look historical.
        msg_records: list[tuple[str, str, str, str, str]] = []
        for days_ago, msgs in data["conversations"]:
            base = datetime.now(IST) - timedelta(days=days_ago)
            for i, (direction, content, sent_by) in enumerate(msgs):
                ts = (base + timedelta(minutes=i * 7)).isoformat()
                msg_records.append((cid, direction, content, sent_by, ts))

        with get_db() as conn:
            for (cid_, direction, content, sent_by, ts) in msg_records:
                conn.execute(
                    """INSERT INTO messages
                       (workspace_id, contact_id, direction, content, content_type,
                        sent_by, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (WORKSPACE, cid_, direction, content, "text", sent_by, ts),
                )
            # Reset total_messages and last_contacted_at to match
            last_ts = msg_records[-1][4] if msg_records else now_iso()
            conn.execute(
                "UPDATE contacts SET total_messages = ?, last_contacted_at = ?, "
                "last_replied_at = ? WHERE id = ?",
                (len(msg_records), last_ts, last_ts, cid),
            )

        # Optional: mark the bot as paused (human is handling) for this contact
        if data.get("bot_paused"):
            from handoff_manager import trigger_handoff  # noqa: E402
            trigger_handoff(
                contact_id=cid,
                reason=data["bot_paused"],
                triggered_by="manual",
                contact_name=data["name"],
                contact_phone=phone,
                detection_method="manual",
            )

        created += 1
        flag = "  [bot paused]" if data.get("bot_paused") else ""
        print(f"  + {data['name']:35s} {data['stage']:13s} ₹{data['deal_value']:>10,}{flag}")

    print(f"\n  → {created} created, {skipped} skipped")


# ============================================================================
# 3. KNOWLEDGE BASE — Bloom Interiors business knowledge
# ============================================================================

KB_DOCS = [
    {
        "title": "Bloom Interiors — About Us",
        "content": """BLOOM INTERIORS — BANGALORE'S TRUSTED HOME INTERIORS PARTNER

WHO WE ARE
Bloom Interiors is a Bangalore-based interior design studio specialising in
end-to-end home interiors for apartments, villas and independent houses. We've
delivered 240+ homes across Bengaluru since 2018.

OUR STUDIO
2nd Floor, 100 Feet Road, Indiranagar, Bangalore — 560038
Open Mon-Sat, 10am to 7pm. Walk-ins welcome (booking encouraged).

OUR FACTORY
30,000 sqft owned manufacturing unit in Hoskote. ISO-9001 certified. We do not
outsource to third parties — every cabinet, wardrobe and modular unit is
built in-house, which is how we hold the 5-year warranty.

WHAT WE DO
• Modular kitchens (L, U, parallel, island)
• Wardrobes (sliding, swing, walk-in)
• Full-home interiors (kitchen + wardrobes + civil + lighting + decor)
• TV units, study units, bar units, foyer consoles
• Senior-citizen-friendly design (accessibility-focused)
• Kids' rooms (modular, growth-friendly)

DESIGN STYLES WE SPECIALISE IN
Contemporary, Scandinavian/minimal, Modern eclectic, Indian contemporary,
Mediterranean, Industrial. Our designers can adapt to any reference.

LICENCES & PARTNERS
GST registered • MSME certified • Authorised partner for Hettich, Hafele,
Blum, Ebco, Saint-Gobain, Asian Paints Royale Aspira finishes.
""",
    },
    {
        "title": "Bloom Interiors — Pricing Guide (2026)",
        "content": """BLOOM INTERIORS — PRICING GUIDE
All prices include GST and standard installation.

MODULAR KITCHENS (start prices, scope-dependent)
• Basic L-shape (small):           starts at ₹1,40,000
• Standard L/U-shape (medium):     starts at ₹2,40,000
• Premium L/U with island:         starts at ₹3,80,000
• Luxury (imported finishes):      starts at ₹6,00,000

Kitchen pricing depends on: linear feet, shutter finish (membrane / acrylic /
PU / veneer / lacquer), countertop (granite / quartz / Corian), hardware brand
(Hettich / Hafele / Blum), accessories (pull-outs, magic corner, tall units).

WARDROBES
• 6ft sliding wardrobe (mirror):   starts at ₹85,000
• 8ft sliding wardrobe (mirror):   starts at ₹1,15,000
• 8ft swing wardrobe (3-door):     starts at ₹95,000
• Walk-in wardrobe (12x6):         starts at ₹2,40,000

FULL-HOME INTERIORS (turnkey, kitchen + wardrobes + civil + lighting)
• 1BHK (~600 sqft):                ₹4-7 lakh
• 2BHK (~900-1100 sqft):           ₹8-14 lakh
• 3BHK (~1300-1600 sqft):          ₹14-22 lakh
• 4BHK / villa (~2000+ sqft):      ₹22-50 lakh+

PREMIUM ADD-ONS
• Italian travertine veneer:       +₹400-600 / sqft
• Brass profile / inlay work:      +₹3,500-8,000 / running ft
• Corian / quartz countertop upgrade: +₹35,000-90,000
• Imported lighting (Vibia, Flos): quoted on request

WHAT'S INCLUDED IN EVERY QUOTE
✓ Free site visit + design consultation (within 25 km of Indiranagar)
✓ 3D walkthrough of every space (2 design iterations included)
✓ Detailed BOQ (Bill of Quantities) — every item priced individually
✓ Project manager assigned to your home
✓ Weekly progress photos via WhatsApp
✓ 5-year warranty on all modular work
✓ 1-year free service visit

WHAT'S NOT INCLUDED
✗ Civil / electrical / plumbing rework (quoted separately if needed)
✗ Loose furniture (sofas, dining tables, beds — we can source on request)
✗ Curtains / soft furnishings
✗ Appliances (chimney, hob, refrigerator — we recommend brands)

PAYMENT TERMS
Standard: 30% on signing, 30% before factory dispatch, 30% on installation
start, 10% on handover. Custom milestones available for villa projects.

DISCOUNTS
• Referral discount: ₹15,000 off when an existing customer refers you
• Repeat customer: 5% loyalty discount on subsequent projects
• Off-season (Jun-Aug): up to 8% off on full-home packages
""",
    },
    {
        "title": "Bloom Interiors — Process & Timeline",
        "content": """HOW A BLOOM PROJECT WORKS — STEP BY STEP

STEP 1 — FIRST CONVERSATION (Day 0)
You message us on WhatsApp, Instagram or visit the studio. Share your floor
plan, rough budget, and possession timeline. We come back within 24 hrs to
schedule a free site visit + design consultation.

STEP 2 — SITE VISIT + CONSULTATION (Day 2-5)
A senior designer (Mahesh, Aparna or Rakesh) visits your home with our
material library (300+ samples). We measure, discuss your lifestyle, capture
references and photograph the site. Duration: ~90 min.

STEP 3 — 3D DESIGN + QUOTE (Day 7-10)
You receive a detailed 3D walkthrough of every space + a line-item BOQ. Two
free iterations are included — most clients lock the design by iteration 2.

STEP 4 — CONTRACT + TOKEN (Day 12-14)
Once you approve the design and BOQ, we sign a fixed-price contract. 30%
token unlocks material procurement.

STEP 5 — FACTORY PRODUCTION (Week 3-6)
All carcasses, shutters, wardrobes are manufactured at our Hoskote unit.
You'll receive weekly progress photos every Friday — automated.

STEP 6 — SITE INSTALLATION (Week 6-8)
Our installation team takes over the home for 7-12 days (depending on scope).
Project manager updates daily. You can drop in any time.

STEP 7 — HANDOVER + WARRANTY (Week 8)
Final walkthrough with you. 10% balance on satisfactory handover. Warranty
papers handed over on the spot.

STEP 8 — POST-HANDOVER (Year 1+)
Free service visit at 3 months and 12 months. Lifetime customer support.
5-year warranty on all modular work.

TYPICAL TIMELINES (from contract signing to handover)
• Modular kitchen only:            4-5 weeks
• Modular kitchen + 2 wardrobes:   5-6 weeks
• 2BHK full-home:                  7-9 weeks
• 3BHK full-home:                  8-10 weeks
• Villa / 4BHK full-home:          10-14 weeks

NOTE ON RUSH PROJECTS
We can compress timelines by 20-25% for an additional 8-10% rush fee, subject
to factory capacity.
""",
    },
    {
        "title": "Bloom Interiors — Frequently Asked Questions",
        "content": """FREQUENTLY ASKED QUESTIONS

Q: Do you charge for the first design + quote?
A: No. The site visit, 3D walkthrough and detailed BOQ are completely free,
   with two design iterations included. You only pay if you sign the contract.

Q: What's your warranty cover?
A: 5-year warranty on all modular work (kitchens, wardrobes, units). Covers
   carcass integrity, hinge/slide hardware, shutter delamination, and
   workmanship defects. Excludes physical damage and water seepage from
   external sources.

Q: Do you do civil / plumbing / electrical work?
A: We do minor civil rework (false ceiling, partition, paint touch-up) as
   part of full-home projects. Major civil is quoted separately. We coordinate
   with your electrician/plumber but don't directly hire one — this keeps
   our liability clean.

Q: Can I see real homes you've done?
A: Yes — our 3 model homes in Indiranagar studio are open Mon-Sat. We can
   also arrange visits to recently-completed customer homes (with their
   permission) in your locality.

Q: How do you handle damages during installation?
A: All site work is fully insured. If any existing furniture, flooring or
   fittings is damaged by our team, we cover full replacement. This is in
   the contract.

Q: What if I want to add or change something mid-project?
A: We have a formal change-order process. You request the change, we quote
   the delta + impact on timeline, you approve in writing, we execute. No
   verbal changes — protects both sides.

Q: Do you work with my own contractor / architect?
A: Yes, we collaborate with external architects regularly. We can either
   execute their drawings or co-design.

Q: How are payments handled?
A: 4-milestone structure (30/30/30/10) by default, fully on the contract.
   Bank transfer, UPI, or cheque. We do not accept cash for amounts > ₹2L
   (legal compliance). Invoice + GST receipt for every milestone.

Q: What if I'm not happy with the final result?
A: You don't pay the final 10% until you sign off. We have a structured
   snag-list process: any defects identified at handover are fixed within
   7 days, then you release the balance.

Q: Are your materials genuine / branded?
A: Yes — we are authorised partners for Hettich, Hafele, Blum (hardware),
   Saint-Gobain (mirrors/glass), Asian Paints Royale Aspira (PU finishes).
   Brand stickers on every component. Invoices on demand.

Q: I'm an NRI / investor — can you handle the project remotely?
A: Yes. We've done 18 NRI projects. You get a dedicated project manager,
   daily WhatsApp updates with photos, and weekly Zoom walkthroughs.
""",
    },
    {
        "title": "Bloom Interiors — Customer Testimonials & Case Studies",
        "content": """RECENT CUSTOMER PROJECTS

────────────────────────────────────────────────────────────
PROJECT 1 — Iyer Family, Sobha Dream Acres
3BHK, 1450 sqft full-home interiors. ₹18.5L. Delivered in 8 weeks.
Style: Modern eclectic, navy + brass kitchen, oak veneer accents.
"Mahesh and team were spectacular. The weekly photo updates kept us in
the loop without us having to chase. Quality of finish is exceptional —
we've already recommended Bloom to two friends." — Aishwarya Iyer

────────────────────────────────────────────────────────────
PROJECT 2 — Bhandari Family, Prestige Lakeside Habitat (Repeat customer)
Modular kitchen + 2 wardrobes. ₹5.8L. Delivered in 5 weeks.
Style: Matte white + walnut. Same as their earlier Bloom project.
"This is our second project with Bloom. They remembered our exact finish
spec from 2 years ago without us having to dig out paperwork. That's
the kind of attention they bring." — Rohit Bhandari

────────────────────────────────────────────────────────────
PROJECT 3 — Captain Krishnan, Adarsh Palm Retreat
Senior-citizen-friendly modular kitchen + wardrobe. ₹4.2L. Delivered in 4 weeks.
Style: Classic, low-counter, easy-grip handles, pull-down upper shelves.
"At 74, I appreciated that Bloom listened to the small accessibility
requests without treating them as exotic. The pull-down shelves have
already saved my back." — Capt. (Retd.) S. Krishnan

────────────────────────────────────────────────────────────
PROJECT 4 — Goyal Family, Embassy Pristine Villa
4BHK villa, 3400 sqft. Premium full-home with imported finishes. ₹38L.
Delivered in 14 weeks.
Style: Travertine + brass + Italian veneer, statement bar, library.
"Worth every rupee. The travertine kitchen is the centerpiece of the
home. Bloom's coordination with our architect was seamless." — Dr. Goyal

────────────────────────────────────────────────────────────
KEY METRICS (last 12 months, 84 completed projects)
• On-time delivery rate:           94%
• Customer satisfaction (post-handover survey): 4.7/5
• Snag-free first-handover rate:   71%
• Repeat / referral business:      48% of new contracts
• Avg project value:               ₹8.4L
""",
    },
]


def seed_kb() -> None:
    """Seed Bloom Interiors knowledge base into SQLite + ChromaDB."""
    try:
        import knowledge_base as kb  # type: ignore
    except Exception as e:
        print(f"  ! knowledge_base unavailable: {e}")
        return

    seeded = 0
    for d in KB_DOCS:
        try:
            kb.add_document(
                title=d["title"],
                content=d["content"],
                doc_type="text",
                scope="global",
            )
            seeded += 1
            print(f"  + {d['title']}")
        except Exception as e:
            print(f"  ! {d['title']} — {e}")

    print(f"\n  → {seeded} KB documents seeded")

    # Also write a refreshed knowledge_base.txt (Quick Edit content) so the
    # KB page's text-area defaults to Bloom Interiors content.
    quick_edit = (
        "# Bloom Interiors — Quick Reference\n\n"
        "Bloom Interiors is a Bangalore-based interior design studio. We do "
        "modular kitchens, wardrobes and full-home interiors for apartments, "
        "villas and independent houses. Studio: 100 Feet Road, Indiranagar. "
        "Factory: 30,000 sqft in Hoskote.\n\n"
        "## Quick price reference\n"
        "- Modular kitchen: starts ₹1.4L (basic) — ₹6L+ (luxury)\n"
        "- Wardrobes: ₹85K (6ft sliding) — ₹2.4L (walk-in)\n"
        "- Full-home 2BHK: ₹8-14L\n"
        "- Full-home 3BHK: ₹14-22L\n"
        "- Full-home 4BHK / villa: ₹22-50L+\n\n"
        "## Always offer\n"
        "- Free site visit + 3D consultation\n"
        "- 5-year warranty on modular work\n"
        "- Weekly WhatsApp progress photos\n"
        "- 4-milestone payment (30/30/30/10)\n\n"
        "## Don't promise\n"
        "- Sub-₹10L for any 3BHK full-home (we won't meet our quality bar)\n"
        "- Same-week site visits (we typically book 3-5 days out)\n"
        "- Civil/plumbing/electrical as a separate scope (we coordinate, not execute)\n"
    )
    (DATA / "knowledge_base.txt").write_text(quick_edit)
    print("  → Quick Edit content updated")


# ============================================================================
# 4. TEMPLATES — Bloom Interiors WhatsApp templates
# ============================================================================

TEMPLATES = [
    {
        "name": "first_enquiry_welcome",
        "category": "utility",
        "body": "Hi {{1}}, thanks for reaching out to Bloom Interiors. To send you the most accurate quote, could you share: (1) the property name, (2) carpet area, (3) what you're looking at — kitchen / wardrobes / full-home, and (4) rough possession date?",
        "variables": ["customer_name"],
        "description": "First reply to an inbound WhatsApp lead",
        "language": "en",
        "usage_count": 312,
    },
    {
        "name": "site_visit_confirmation",
        "category": "utility",
        "body": "Site visit confirmed, {{1}}. {{2}} (Senior Designer) will be at {{3}} on {{4}} at {{5}}. He'll bring our material library and 2 reference projects from your community. Please reply if anything changes.",
        "variables": ["customer_name", "designer_name", "address", "date", "time"],
        "description": "Confirms a booked design consultation",
        "language": "en",
        "usage_count": 187,
    },
    {
        "name": "quote_sent",
        "category": "utility",
        "body": "Hi {{1}}, your detailed quote and 3D walkthrough are ready. Total: ₹{{2}} (incl. GST). PDF attached. Two design iterations included — happy to refine. When would be a good time to walk you through it?",
        "variables": ["customer_name", "quote_amount"],
        "description": "Sent when a quote is shared with the customer",
        "language": "en",
        "usage_count": 96,
    },
    {
        "name": "weekly_progress_photo",
        "category": "utility",
        "body": "Week {{1}} update for your {{2}} project: {{3}}. Photos attached. Next milestone: {{4}}. Reply with any questions or change requests.",
        "variables": ["week_number", "project_name", "current_status", "next_milestone"],
        "description": "Automated weekly project update with photos",
        "language": "en",
        "usage_count": 421,
    },
    {
        "name": "payment_milestone_due",
        "category": "utility",
        "body": "Hi {{1}}, friendly reminder — milestone {{2}} of {{3}} (₹{{4}}) is due on {{5}}. Pay securely here: {{6}}. Receipt + GST invoice will be sent within 1 hr of payment.",
        "variables": ["customer_name", "milestone_no", "milestone_total", "amount", "due_date", "payment_link"],
        "description": "Payment milestone reminder",
        "language": "en",
        "usage_count": 58,
    },
    {
        "name": "festive_kitchen_offer",
        "category": "marketing",
        "body": "Diwali special, {{1}} — flat ₹{{2}} off all modular kitchens signed before {{3}}. Includes upgrade to soft-close hardware (worth ₹18,000) at no cost. Visit our Indiranagar studio or reply with your floor plan to lock the offer.",
        "variables": ["customer_name", "discount_amount", "expiry_date"],
        "description": "Seasonal modular kitchen promotion",
        "language": "en",
        "usage_count": 264,
    },
    {
        "name": "post_handover_feedback",
        "category": "utility",
        "body": "Hi {{1}}, we hope you're loving your new home. It's been 30 days since handover — could you take 1 minute to rate your experience (1-5)? Your feedback shapes how we serve the next family.",
        "variables": ["customer_name"],
        "description": "30-day post-handover feedback request",
        "language": "en",
        "usage_count": 71,
    },
]


def seed_templates() -> None:
    try:
        import template_manager as tm  # type: ignore
    except Exception as e:
        print(f"  ! template_manager unavailable: {e}")
        return

    seeded = 0
    for t in TEMPLATES:
        existing = tm.get_template_by_name(t["name"])
        if existing:
            print(f"  · {t['name']} (already exists)")
            continue
        try:
            created = tm.create_template(
                name=t["name"],
                body=t["body"],
                category=t["category"],
                variables=t["variables"],
                description=t["description"],
                language=t["language"],
            )
            try:
                tm.update_template(created["id"], approval_status="approved")
            except Exception:
                pass
            seeded += 1
            print(f"  + {t['name']}")
        except Exception as e:
            print(f"  ! {t['name']} — {e}")

    # Inject realistic usage stats into templates.json
    tpls_path = DATA / "templates.json"
    if tpls_path.exists():
        try:
            arr = json.loads(tpls_path.read_text())
            stats_map = {t["name"]: t["usage_count"] for t in TEMPLATES}
            for tpl in arr:
                u = stats_map.get(tpl["name"])
                if u is None:
                    continue
                tpl["usage_count"] = u
                tpl["delivered_count"] = int(u * 0.97)
                tpl["read_count"] = int(u * 0.86)
                tpl["replied_count"] = int(u * 0.34)
                tpl["reply_rate"] = round(tpl["replied_count"] / max(u, 1), 2)
            tpls_path.write_text(json.dumps(arr, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"  ! could not patch usage stats: {e}")

    print(f"\n  → {seeded} templates seeded")


# ============================================================================
# 5. CAMPAIGNS — broadcast campaigns into the campaigns SQLite table
# ============================================================================

def seed_campaigns() -> None:
    try:
        import outbound  # type: ignore
    except Exception as e:
        print(f"  ! outbound unavailable: {e}")
        return

    # Need contact IDs (some campaigns target specific contacts)
    contacts = list_contacts(workspace_id=WORKSPACE)
    won_lost_ids = [c["contact_id"] for c in contacts if c.get("pipeline_stage") in ("Won", "Lost")]
    qualified_ids = [c["contact_id"] for c in contacts if c.get("pipeline_stage") in ("Qualified", "Proposal")]

    campaigns = [
        {
            "name": "Diwali 2025 — Modular Kitchen Special",
            "template_name": "festive_kitchen_offer",
            "template_id": "tpl_festive_kitchen",
            "target_count": 264,
            "sent": 264, "failed": 6, "delivered": 258, "read": 221, "replied": 47,
            "filter_stage": "", "filter_tag": "all",
            "scheduled_at": "", "status": "completed",
            "created_at": now_iso(days_ago=21),
            "completed_at": now_iso(days_ago=21),
        },
        {
            "name": "Q1 Win-back — Lost Leads (Quality story)",
            "template_name": "first_enquiry_welcome",
            "template_id": "tpl_winback",
            "target_count": max(1, len(won_lost_ids) or 1),
            "sent": 1, "failed": 0, "delivered": 1, "read": 1, "replied": 0,
            "filter_stage": "Lost", "filter_tag": "",
            "contact_ids": won_lost_ids[:5],
            "scheduled_at": "", "status": "completed",
            "created_at": now_iso(days_ago=11),
            "completed_at": now_iso(days_ago=11),
        },
        {
            "name": "April Project Updates — Active Customers",
            "template_name": "weekly_progress_photo",
            "template_id": "tpl_progress",
            "target_count": 12,
            "sent": 12, "failed": 0, "delivered": 12, "read": 11, "replied": 4,
            "filter_stage": "Won", "filter_tag": "",
            "scheduled_at": "", "status": "active",
            "created_at": now_iso(days_ago=2),
            "completed_at": "",
        },
        {
            "name": "Summer Off-Season — 8% Off Full-home Packages",
            "template_name": "festive_kitchen_offer",
            "template_id": "tpl_summer",
            "target_count": max(1, len(qualified_ids)),
            "sent": 0, "failed": 0, "delivered": 0, "read": 0, "replied": 0,
            "filter_stage": "Qualified", "filter_tag": "",
            "contact_ids": qualified_ids,
            "scheduled_at": now_iso(days_ago=-3),  # 3 days from now
            "status": "scheduled",
            "created_at": now_iso(days_ago=1),
            "completed_at": "",
        },
    ]

    seeded = 0
    for c in campaigns:
        try:
            campaign_id = f"cmp_{uuid.uuid4().hex[:8]}"
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO campaigns
                       (id, workspace_id, name, template_id, template_name, target_count,
                        sent, failed, delivered, read_count, replied, not_on_whatsapp,
                        filter_stage, filter_tag, contact_ids, reply_mode, campaign_kb,
                        status, scheduled_at, created_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        campaign_id, WORKSPACE, c["name"], c["template_id"], c["template_name"],
                        c["target_count"], c["sent"], c["failed"], c["delivered"],
                        c["read"], c["replied"], 0,
                        c.get("filter_stage", ""), c.get("filter_tag", ""),
                        json.dumps(c.get("contact_ids", [])),
                        "auto_ai", 0,
                        c["status"], c.get("scheduled_at", ""),
                        c["created_at"], c.get("completed_at", ""),
                    ),
                )
            seeded += 1
            label = c["status"].upper()
            print(f"  + [{label:>9s}] {c['name']}")
        except Exception as e:
            print(f"  ! {c['name']} — {e}")

    print(f"\n  → {seeded} campaigns seeded")


# ============================================================================
# 6. ANALYTICS EVENTS — 30 days into per-day jsonl files
# ============================================================================

def seed_analytics_events() -> None:
    """Generate 30 days of realistic events into per-day jsonl files."""
    analytics_dir = DATA / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(7)
    contacts = list_contacts(workspace_id=WORKSPACE)
    contact_ids = [c["contact_id"] for c in contacts] or ["unknown"]

    # Hour-of-day weights — interior business is active 9am-9pm IST
    hour_weights = [
        1, 1, 1, 1, 1, 1,   # 00-05
        2, 4, 8, 14, 18, 22,  # 06-11
        20, 16, 14, 18, 22, 24,  # 12-17
        20, 16, 12, 8, 4, 2,  # 18-23
    ]

    # Event mix
    event_types = [
        ("message_received", 0.32),
        ("message_sent",     0.28),
        ("ai_reply_generated", 0.20),
        ("contact_created",  0.05),
        ("stage_changed",    0.06),
        ("handoff_triggered", 0.04),
        ("template_sent",    0.03),
        ("campaign_sent",    0.01),
        ("deal_won",         0.01),
    ]

    total = 0
    now = datetime.now(IST)
    for days_ago in range(30, -1, -1):
        date_obj = now - timedelta(days=days_ago)
        date_str = date_obj.strftime("%Y-%m-%d")
        # Vary daily volume — weekdays busier than weekends
        is_weekend = date_obj.weekday() >= 5
        base = rng.randint(70, 130) if not is_weekend else rng.randint(40, 80)
        # Recent days slightly busier (growth trend)
        growth_factor = 1 + (30 - days_ago) * 0.012
        daily = int(base * growth_factor)

        lines = []
        for _ in range(daily):
            r = rng.random()
            cum = 0.0
            chosen = "message_received"
            for et, w in event_types:
                cum += w
                if r <= cum:
                    chosen = et
                    break

            hour = rng.choices(range(24), weights=hour_weights, k=1)[0]
            minute = rng.randint(0, 59)
            second = rng.randint(0, 59)
            ts = date_obj.replace(hour=hour, minute=minute, second=second, microsecond=0).isoformat()

            entry = {
                "ts": ts,
                "date": date_str,
                "hour": hour,
                "event": chosen,
                "type": chosen,  # alias for bulk-loader compat
                "contact_id": rng.choice(contact_ids),
                "workspace_id": WORKSPACE,
            }
            lines.append(json.dumps(entry, ensure_ascii=False))

        path = analytics_dir / f"{date_str}.jsonl"
        path.write_text("\n".join(lines) + "\n")
        total += len(lines)

    print(f"  → {total} events written across 31 days")


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Bloom Interiors demo data.")
    parser.add_argument("--keep", action="store_true",
                        help="Don't wipe existing data; only add missing items.")
    args = parser.parse_args()

    if not args.keep:
        banner("1. WIPE — clearing existing contacts, KB, campaigns, analytics")
        wipe_all_contacts()
        wipe_kb_and_campaigns()

    banner("2. CONTACTS + CONVERSATIONS — Bloom Interiors customer base")
    seed_contacts()

    banner("3. KNOWLEDGE BASE — Bloom Interiors business knowledge")
    seed_kb()

    banner("4. TEMPLATES — WhatsApp templates with usage stats")
    seed_templates()

    banner("5. CAMPAIGNS — broadcasts (1 scheduled, 1 active, 2 completed)")
    seed_campaigns()

    banner("6. ANALYTICS EVENTS — 30 days of trend data")
    seed_analytics_events()

    banner("DONE — Bloom Interiors demo is ready")
    print("""
Your dashboard now reflects a real interior design studio:

  • 12 customers across 6 pipeline stages (₹1.13Cr+ pipeline value)
  • 5 KB documents about Bloom Interiors (about, pricing, process, FAQs, testimonials)
  • 7 WhatsApp templates with realistic usage stats
  • 4 campaigns (1 scheduled, 1 active, 2 completed)
  • 31 days of analytics events (charts and trends)

Open the dashboard, click around — every screen now tells the same story.
""")


if __name__ == "__main__":
    main()
