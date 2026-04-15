"""
Nazar — Onboarding Manager

Tracks and guides new workspace setup through a structured wizard.

Steps:
  1. account_created    — workspace + owner account exist
  2. business_info      — business name, language, persona configured
  3. knowledge_base     — at least some KB content added
  4. whatsapp_connect   — WhatsApp number connected (or skipped for demo)
  5. llm_configured     — at least one LLM API key working
  6. first_contact      — at least one contact added
  7. first_message      — first test/simulated message sent
  8. team_invited       — at least one team member invited (or skipped)
  9. complete           — all required steps done

Storage: data/onboarding/{workspace_id}.json
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "onboarding"

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

ONBOARDING_STEPS = [
    {
        "id": "account_created",
        "title": "Create your account",
        "description": "Set up your Nazar workspace.",
        "required": True,
        "skippable": False,
        "order": 1,
    },
    {
        "id": "business_info",
        "title": "Configure your business",
        "description": "Set your business name, persona, and welcome message so the AI knows who it is.",
        "required": True,
        "skippable": False,
        "order": 2,
    },
    {
        "id": "knowledge_base",
        "title": "Add your knowledge base",
        "description": "Paste your FAQs, pricing, and product info so the AI can answer customer questions accurately.",
        "required": True,
        "skippable": False,
        "order": 3,
    },
    {
        "id": "llm_configured",
        "title": "Connect your AI provider",
        "description": "Add your OpenRouter, Anthropic, or Google API key to power the AI.",
        "required": True,
        "skippable": False,
        "order": 4,
    },
    {
        "id": "first_contact",
        "title": "Add your first contact",
        "description": "Import contacts from CSV or add one manually to get started.",
        "required": True,
        "skippable": False,
        "order": 5,
    },
    {
        "id": "first_message",
        "title": "Send a test message",
        "description": "Use the Simulation mode to test the AI on a real customer message without WhatsApp.",
        "required": True,
        "skippable": False,
        "order": 6,
    },
    {
        "id": "whatsapp_connect",
        "title": "Connect WhatsApp",
        "description": "Link your WhatsApp Business number to start receiving and sending real messages.",
        "required": False,
        "skippable": True,
        "order": 7,
    },
    {
        "id": "team_invited",
        "title": "Invite your team",
        "description": "Add team members so they can handle handoffs and manage the pipeline.",
        "required": False,
        "skippable": True,
        "order": 8,
    },
]

REQUIRED_STEPS = {s["id"] for s in ONBOARDING_STEPS if s["required"]}
ALL_STEP_IDS = {s["id"] for s in ONBOARDING_STEPS}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(workspace_id: str) -> Path:
    _ensure_dir()
    return DATA_DIR / f"{workspace_id}.json"


def _load(workspace_id: str) -> dict:
    p = _path(workspace_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _init_state(workspace_id)


def _save(workspace_id: str, state: dict):
    _path(workspace_id).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _init_state(workspace_id: str) -> dict:
    """Create a fresh onboarding state."""
    now = datetime.now(IST).isoformat()
    return {
        "workspace_id": workspace_id,
        "started_at": now,
        "completed_at": None,
        "is_complete": False,
        "steps": {
            s["id"]: {
                "id": s["id"],
                "title": s["title"],
                "done": False,
                "skipped": False,
                "done_at": None,
                "required": s["required"],
                "skippable": s["skippable"],
                "order": s["order"],
            }
            for s in ONBOARDING_STEPS
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_onboarding_state(workspace_id: str) -> dict:
    """
    Get the full onboarding state for a workspace.

    Includes progress, steps, completion status, and next step.
    """
    state = _load(workspace_id)
    steps = state["steps"]

    completed_required = sum(
        1 for sid in REQUIRED_STEPS if steps.get(sid, {}).get("done")
    )
    total_required = len(REQUIRED_STEPS)
    progress_pct = round(completed_required / max(total_required, 1) * 100)

    # Next incomplete step
    next_step = None
    for s in sorted(ONBOARDING_STEPS, key=lambda x: x["order"]):
        step_state = steps.get(s["id"], {})
        if not step_state.get("done") and not step_state.get("skipped"):
            next_step = s["id"]
            break

    return {
        **state,
        "steps_list": sorted(
            [
                {**steps.get(s["id"], {}), **{k: v for k, v in s.items() if k not in steps.get(s["id"], {})}}
                for s in ONBOARDING_STEPS
            ],
            key=lambda x: x.get("order", 99),
        ),
        "progress_pct": progress_pct,
        "completed_required": completed_required,
        "total_required": total_required,
        "next_step": next_step,
    }


def mark_step_done(workspace_id: str, step_id: str) -> dict:
    """
    Mark an onboarding step as completed.

    Returns the updated onboarding state.
    Raises ValueError if step_id is unknown.
    """
    if step_id not in ALL_STEP_IDS:
        raise ValueError(f"Unknown onboarding step: {step_id}")

    state = _load(workspace_id)
    now = datetime.now(IST).isoformat()
    state["steps"][step_id]["done"] = True
    state["steps"][step_id]["skipped"] = False
    state["steps"][step_id]["done_at"] = now

    # Check if all required steps are done
    if all(state["steps"].get(sid, {}).get("done") for sid in REQUIRED_STEPS):
        state["is_complete"] = True
        state["completed_at"] = now
        logger.info(f"Onboarding complete for workspace {workspace_id}")

    _save(workspace_id, state)
    return get_onboarding_state(workspace_id)


def skip_step(workspace_id: str, step_id: str) -> dict:
    """
    Skip an optional onboarding step.

    Raises ValueError if step is required (cannot be skipped).
    Returns the updated onboarding state.
    """
    if step_id not in ALL_STEP_IDS:
        raise ValueError(f"Unknown onboarding step: {step_id}")

    step_def = next(s for s in ONBOARDING_STEPS if s["id"] == step_id)
    if not step_def.get("skippable"):
        raise ValueError(f"Step '{step_id}' cannot be skipped — it is required")

    state = _load(workspace_id)
    state["steps"][step_id]["skipped"] = True
    state["steps"][step_id]["done_at"] = datetime.now(IST).isoformat()
    _save(workspace_id, state)
    return get_onboarding_state(workspace_id)


def reset_onboarding(workspace_id: str) -> dict:
    """Reset onboarding to the beginning (for re-runs / testing)."""
    state = _init_state(workspace_id)
    _save(workspace_id, state)
    return get_onboarding_state(workspace_id)


# ---------------------------------------------------------------------------
# Auto-detect from system state
# ---------------------------------------------------------------------------

def auto_detect_progress(workspace_id: str) -> dict:
    """
    Auto-detect which onboarding steps have been completed by checking
    system state (config, contacts, KB, LLM health, etc.).

    Useful on login to compute real progress without manual step marking.
    Returns the updated onboarding state.
    """
    import os
    from pathlib import Path as P

    base = P(__file__).parent.parent

    # Step: account_created — always true if we're running
    mark_step_done(workspace_id, "account_created")

    # Step: business_info — config has a non-empty business_name
    config_path = base / "data" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            if cfg.get("business_name") and cfg["business_name"] not in ("", "Nazar Demo", "our company"):
                mark_step_done(workspace_id, "business_info")
        except Exception:
            pass

    # Step: knowledge_base — KB file has content
    kb_path = base / "data" / "knowledge_base.txt"
    if kb_path.exists() and kb_path.stat().st_size > 100:
        mark_step_done(workspace_id, "knowledge_base")

    # Step: llm_configured — at least one LLM key in env
    llm_keys = ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
    if any(os.environ.get(k) for k in llm_keys):
        mark_step_done(workspace_id, "llm_configured")

    # Step: first_contact — contacts directory has at least one contact
    contacts_dir = base / "data" / "contacts"
    phone_index = contacts_dir / ".phone_index.json"
    if phone_index.exists():
        try:
            idx = json.loads(phone_index.read_text())
            if len(idx) >= 1:
                mark_step_done(workspace_id, "first_contact")
        except Exception:
            pass

    # Step: whatsapp_connect
    if os.environ.get("WA_ACCESS_TOKEN") and os.environ.get("WA_PHONE_NUMBER_ID"):
        mark_step_done(workspace_id, "whatsapp_connect")

    return get_onboarding_state(workspace_id)


def get_readiness_checklist(workspace_id: str) -> dict:
    """
    Generate a pre-launch readiness checklist for the workspace.

    Returns a list of items that must be confirmed before going live.
    """
    import os
    from pathlib import Path as P

    base = P(__file__).parent.parent
    checks = []

    # 1. LLM provider
    llm_keys = ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
    has_llm = any(os.environ.get(k) for k in llm_keys)
    checks.append({
        "id": "llm_provider",
        "label": "AI provider configured",
        "passed": has_llm,
        "critical": True,
        "fix": "Add an OpenRouter or Anthropic API key in Settings → API Keys",
    })

    # 2. Business name
    business_name = ""
    config_path = base / "data" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            business_name = cfg.get("business_name", "")
        except Exception:
            pass
    checks.append({
        "id": "business_name",
        "label": "Business name configured",
        "passed": bool(business_name and business_name not in ("", "Nazar Demo")),
        "critical": True,
        "fix": "Set your business name in Settings → Business",
    })

    # 3. Knowledge base
    kb_path = base / "data" / "knowledge_base.txt"
    has_kb = kb_path.exists() and kb_path.stat().st_size > 100
    checks.append({
        "id": "knowledge_base",
        "label": "Knowledge base has content",
        "passed": has_kb,
        "critical": True,
        "fix": "Add your product/pricing info in Knowledge Base",
    })

    # 4. At least one contact
    phone_index = base / "data" / "contacts" / ".phone_index.json"
    has_contacts = False
    if phone_index.exists():
        try:
            idx = json.loads(phone_index.read_text())
            has_contacts = len(idx) >= 1
        except Exception:
            pass
    checks.append({
        "id": "contacts",
        "label": "At least one contact added",
        "passed": has_contacts,
        "critical": True,
        "fix": "Add a contact manually or import via CSV",
    })

    # 5. WhatsApp (optional — can use simulation)
    has_wa = bool(
        os.environ.get("WA_ACCESS_TOKEN") and os.environ.get("WA_PHONE_NUMBER_ID")
    )
    checks.append({
        "id": "whatsapp",
        "label": "WhatsApp Business connected",
        "passed": has_wa,
        "critical": False,
        "fix": "Add your WhatsApp credentials in Settings → WhatsApp (or use Simulation mode)",
    })

    # 6. API key security
    default_key = os.environ.get("NAZAR_API_KEY", "") == "nazar_dev_key"
    checks.append({
        "id": "api_key_security",
        "label": "Dashboard API key changed from default",
        "passed": not default_key,
        "critical": False,
        "fix": "Set a strong NAZAR_API_KEY in your .env file",
    })

    # 7. SOUL persona
    soul_path = base / "agent" / "SOUL.md"
    checks.append({
        "id": "soul_configured",
        "label": "AI persona file present",
        "passed": soul_path.exists(),
        "critical": True,
        "fix": "Ensure agent/SOUL.md exists in the project",
    })

    passed = sum(1 for c in checks if c["passed"])
    critical_failed = sum(1 for c in checks if c["critical"] and not c["passed"])
    ready = critical_failed == 0

    return {
        "ready": ready,
        "passed": passed,
        "total": len(checks),
        "critical_failures": critical_failed,
        "score": round(passed / max(len(checks), 1) * 100),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    # Clean
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    ws = "ws_test123"

    # 1. Initial state
    state = get_onboarding_state(ws)
    assert state["is_complete"] is False
    assert state["progress_pct"] == 0
    assert state["next_step"] == "account_created"
    print(f"✅ Initial state: {state['progress_pct']}% complete")

    # 2. Mark steps
    mark_step_done(ws, "account_created")
    mark_step_done(ws, "business_info")
    state2 = get_onboarding_state(ws)
    assert state2["steps"]["account_created"]["done"] is True
    assert state2["progress_pct"] > 0
    print(f"✅ After 2 steps: {state2['progress_pct']}% complete")

    # 3. Skip optional step
    skip_step(ws, "whatsapp_connect")
    state3 = get_onboarding_state(ws)
    assert state3["steps"]["whatsapp_connect"]["skipped"] is True
    print("✅ Optional step skipped")

    # 4. Cannot skip required step
    try:
        skip_step(ws, "knowledge_base")
        print("FAIL: should have raised ValueError")
    except ValueError:
        print("✅ Required step cannot be skipped")

    # 5. Complete all required steps
    for sid in REQUIRED_STEPS:
        mark_step_done(ws, sid)
    final = get_onboarding_state(ws)
    assert final["is_complete"] is True
    assert final["progress_pct"] == 100
    print(f"✅ Onboarding complete! Steps done: {final['completed_required']}/{final['total_required']}")

    # 6. Reset
    reset_onboarding(ws)
    reset_state = get_onboarding_state(ws)
    assert reset_state["is_complete"] is False
    print("✅ Reset works")

    # 7. Readiness checklist
    checklist = get_readiness_checklist(ws)
    assert "checks" in checklist
    assert "ready" in checklist
    print(f"✅ Readiness checklist: score={checklist['score']}%, ready={checklist['ready']}")
    for c in checklist["checks"]:
        status = "✅" if c["passed"] else ("❌" if c["critical"] else "⚠️")
        print(f"  {status} {c['label']}")

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\n✅ All onboarding tests passed!")
