"""
Nazar — WhatsApp Template Manager

Manages WhatsApp message templates:
1. Template library — pre-tested, high-approval-rate templates
2. Template CRUD — create, edit, delete, track usage
3. Approval status tracking (pending → approved → rejected)
4. Auto-suggestion based on customer context
5. Variable interpolation for template sends
6. Rich template components: header, body, footer, buttons

WhatsApp Business API requires pre-approved templates for
initiating conversations outside the 24-hour window. This module
manages the template lifecycle.

Storage: data/templates.json
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

# Template categories allowed by Meta
TEMPLATE_CATEGORIES = ["marketing", "utility", "authentication"]

# Header types allowed by Meta
HEADER_TYPES = ["none", "text", "image", "video", "document"]

# Button types allowed by Meta
BUTTON_TYPES = ["quick_reply", "url", "phone"]

# Pre-built template library with high approval rates
DEFAULT_TEMPLATES = [
    {
        "id": "tpl_welcome",
        "name": "welcome_new_lead",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Hi {{1}}! Thanks for your interest in our services. I'm here to help you find the right solution. What are you looking for?",
        "footer": "",
        "buttons": [],
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Welcome message for new leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_followup",
        "name": "gentle_followup",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Hi {{1}}, just checking in! We discussed {{2}} recently. Do you have any questions or would you like to proceed?",
        "footer": "",
        "buttons": [{"type": "quick_reply", "text": "Yes, let's proceed"}, {"type": "quick_reply", "text": "Not now"}],
        "variables": ["name", "topic"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Gentle follow-up for warm leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_demo_invite",
        "name": "demo_invitation",
        "category": "utility",
        "header": {"type": "text", "text": "Demo Invitation 🎯"},
        "body": "Hi {{1}}! Based on our conversation, I think a quick demo would help. Would you like to schedule a 15-minute walkthrough? I'm available this week.",
        "footer": "Reply STOP to opt out",
        "buttons": [{"type": "quick_reply", "text": "Schedule Demo"}, {"type": "quick_reply", "text": "Maybe Later"}],
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Demo invitation for interested leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_proposal",
        "name": "proposal_sent",
        "category": "utility",
        "header": {"type": "text", "text": "Your Proposal is Ready! 📋"},
        "body": "Hi {{1}}, I've prepared a proposal for {{2}} based on your requirements. Would you like me to walk you through it or shall I send it over?",
        "footer": "",
        "buttons": [{"type": "quick_reply", "text": "Walk me through"}, {"type": "quick_reply", "text": "Send it over"}],
        "variables": ["name", "company"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Notify about proposal readiness",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_seasonal",
        "name": "seasonal_greeting",
        "category": "marketing",
        "header": {"type": "text", "text": "🎉 Season's Greetings!"},
        "body": "Hi {{1}}! Wishing you a wonderful season ahead. We have some exciting updates we'd love to share. Can I tell you more?",
        "footer": "Reply STOP to unsubscribe",
        "buttons": [{"type": "quick_reply", "text": "Tell me more!"}, {"type": "quick_reply", "text": "Not interested"}],
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Seasonal/festive re-engagement",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_feedback",
        "name": "feedback_request",
        "category": "utility",
        "header": {"type": "none"},
        "body": "Hi {{1}}! It's been a while since we connected. How's everything going? We'd love to hear your feedback and see if there's anything we can help with.",
        "footer": "",
        "buttons": [],
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Feedback request for won customers",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_hindi_welcome",
        "name": "welcome_hindi",
        "category": "utility",
        "header": {"type": "none"},
        "body": "नमस्ते {{1}}! हमारी सर्विसेज में आपकी रुचि के लिए धन्यवाद। मैं आपकी सही समाधान खोजने में मदद करने के लिए यहाँ हूँ। आपको क्या चाहिए?",
        "footer": "",
        "buttons": [],
        "variables": ["name"],
        "language": "hi",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Hindi welcome message",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_reengagement",
        "name": "win_back",
        "category": "marketing",
        "header": {"type": "text", "text": "We miss you! 💙"},
        "body": "Hi {{1}}, we haven't heard from you in a while! We've made some improvements since we last spoke. Would you be open to a quick catch-up?",
        "footer": "Reply STOP to unsubscribe",
        "buttons": [{"type": "quick_reply", "text": "Sure, let's chat"}, {"type": "url", "text": "Visit Website", "url": "https://example.com"}],
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": "Win-back for dormant contacts",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
]


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _templates_path() -> Path:
    """Path to templates storage."""
    return DATA_DIR / "templates.json"


def _load_templates() -> list:
    """Load templates from disk. Initializes with defaults if missing."""
    path = _templates_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Initialize with default library
    _save_templates(DEFAULT_TEMPLATES)
    return DEFAULT_TEMPLATES.copy()


def _save_templates(templates: list):
    """Save templates to disk."""
    path = _templates_path()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------

def list_templates(
    category: Optional[str] = None,
    status: Optional[str] = None,
) -> list:
    """
    List all templates, optionally filtered by category or approval status.

    Args:
        category: Filter by "marketing", "utility", or "authentication".
        status: Filter by "pending", "approved", or "rejected".

    Returns:
        List of template dicts.
    """
    templates = _load_templates()

    if category:
        templates = [t for t in templates if t.get("category") == category]
    if status:
        templates = [t for t in templates if t.get("approval_status") == status]

    return templates


def get_template(template_id: str) -> Optional[dict]:
    """Get a template by ID. Returns None if not found."""
    templates = _load_templates()
    for t in templates:
        if t["id"] == template_id:
            return t
    return None


def get_template_by_name(name: str) -> Optional[dict]:
    """Get a template by name. Returns None if not found."""
    templates = _load_templates()
    for t in templates:
        if t["name"] == name:
            return t
    return None


def create_template(
    name: str,
    body: str,
    category: str = "utility",
    variables: Optional[list] = None,
    language: str = "en",
    description: str = "",
    header: Optional[dict] = None,
    footer: str = "",
    buttons: Optional[list] = None,
) -> dict:
    """
    Create a new template.

    Args:
        name: Template name (unique, lowercase, underscores).
        body: Template body text with {{1}}, {{2}} variables.
        category: "marketing", "utility", or "authentication".
        variables: List of variable names for documentation.
        language: ISO language code.
        description: Human-readable description.
        header: Header component dict, e.g. {"type": "text", "text": "Hello"}.
        footer: Footer text (max 60 chars).
        buttons: List of button dicts, e.g. [{"type": "quick_reply", "text": "Yes"}].

    Returns:
        The created template dict.

    Raises:
        ValueError: If name is duplicate or category is invalid.
    """
    if category not in TEMPLATE_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {TEMPLATE_CATEGORIES}"
        )

    templates = _load_templates()

    # Check for duplicate name
    for t in templates:
        if t["name"] == name:
            raise ValueError(f"Template with name '{name}' already exists")

    # Validate header
    if header and header.get("type") not in HEADER_TYPES:
        raise ValueError(f"Invalid header type. Must be one of: {HEADER_TYPES}")

    # Validate buttons (max 3 as per Meta)
    if buttons and len(buttons) > 3:
        raise ValueError("Maximum 3 buttons allowed per template")

    now = datetime.now(IST).isoformat()
    template = {
        "id": f"tpl_{uuid.uuid4().hex[:8]}",
        "name": name,
        "category": category,
        "header": header or {"type": "none"},
        "body": body,
        "footer": footer or "",
        "buttons": buttons or [],
        "variables": variables or [],
        "language": language,
        "approval_status": "pending",
        "usage_count": 0,
        "reply_rate": 0.0,
        "delivered_count": 0,
        "read_count": 0,
        "replied_count": 0,
        "failed_count": 0,
        "description": description,
        "created_at": now,
        "updated_at": now,
    }

    templates.append(template)
    _save_templates(templates)

    logger.info(f"Template created: {name} (id={template['id']})")
    return template


def update_template(template_id: str, **fields) -> dict:
    """
    Update fields on an existing template.

    Returns the updated template dict.
    Raises ValueError if template not found.
    """
    templates = _load_templates()

    for i, t in enumerate(templates):
        if t["id"] == template_id:
            # Validate category if provided
            if "category" in fields and fields["category"] not in TEMPLATE_CATEGORIES:
                raise ValueError(
                    f"Invalid category. Must be one of: {TEMPLATE_CATEGORIES}"
                )
            t.update(fields)
            t["updated_at"] = datetime.now(IST).isoformat()
            templates[i] = t
            _save_templates(templates)
            logger.info(f"Template updated: {t['name']} ({template_id})")
            return t

    raise ValueError(f"Template '{template_id}' not found")


def delete_template(template_id: str):
    """Delete a template by ID."""
    templates = _load_templates()
    templates = [t for t in templates if t["id"] != template_id]
    _save_templates(templates)
    logger.info(f"Template deleted: {template_id}")


def increment_usage(template_id: str):
    """Increment the usage count for a template."""
    templates = _load_templates()
    for t in templates:
        if t["id"] == template_id:
            t["usage_count"] = t.get("usage_count", 0) + 1
            t["updated_at"] = datetime.now(IST).isoformat()
            break
    _save_templates(templates)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_template(template: dict, contact: dict) -> str:
    """
    Render a template body with contact data.

    Replaces {{1}}, {{2}}, etc. with values from the contact
    based on the template's variable definitions.

    Args:
        template: Template dict with body and variables.
        contact: Contact profile dict.

    Returns:
        Rendered message string.

    Raises:
        ValueError: If template has no body text.
    """
    body = template.get("body", "")
    if not body:
        raise ValueError("Template has no body text")

    variables = template.get("variables", [])

    # Map variable names to contact fields with sensible fallbacks
    name_val = contact.get("name") or ""
    if not name_val.strip():
        name_val = "there"

    var_map = {
        "name": name_val,
        "company": contact.get("company") or "your company",
        "phone": contact.get("phone") or "",
        "stage": contact.get("pipeline_stage") or "",
        "deal_value": f"₹{contact.get('deal_value', 0):,.0f}",
        "topic": contact.get("notes") or "our discussion",
    }

    for i, var_name in enumerate(variables, start=1):
        placeholder = "{{" + str(i) + "}}"
        value = var_map.get(var_name, str(var_name))
        body = body.replace(placeholder, value)

    return body


# ---------------------------------------------------------------------------
# Template suggestions
# ---------------------------------------------------------------------------

def suggest_template(
    contact: dict,
    memory_summary: Optional[dict] = None,
) -> Optional[dict]:
    """
    Suggest the best template for a contact based on their pipeline stage
    and memory signals.

    Returns the best matching template dict, or None.
    """
    stage = contact.get("pipeline_stage", "New")
    templates = _load_templates()
    approved = [t for t in templates if t.get("approval_status") == "approved"]

    if not approved:
        return None

    # Stage-based suggestion mapping
    stage_suggestions = {
        "New": ["welcome_new_lead", "welcome_hindi"],
        "Qualified": ["demo_invitation", "gentle_followup"],
        "Proposal": ["proposal_sent", "gentle_followup"],
        "Negotiation": ["gentle_followup", "demo_invitation"],
        "Won": ["feedback_request", "seasonal_greeting"],
        "Lost": ["win_back", "seasonal_greeting"],
    }

    preferred_names = stage_suggestions.get(stage, ["gentle_followup"])

    for name in preferred_names:
        for t in approved:
            if t["name"] == name:
                return t

    # Fallback: return any approved template
    return approved[0] if approved else None


def get_template_stats() -> dict:
    """Get aggregate template statistics."""
    templates = _load_templates()
    return {
        "total": len(templates),
        "approved": len([t for t in templates if t.get("approval_status") == "approved"]),
        "pending": len([t for t in templates if t.get("approval_status") == "pending"]),
        "rejected": len([t for t in templates if t.get("approval_status") == "rejected"]),
        "total_usage": sum(t.get("usage_count", 0) for t in templates),
        "categories": {
            cat: len([t for t in templates if t.get("category") == cat])
            for cat in TEMPLATE_CATEGORIES
        },
    }
