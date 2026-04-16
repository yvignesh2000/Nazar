"""
Nazar — Meta WhatsApp Template Sync

Manages the lifecycle of WhatsApp templates with Meta's Cloud API:
1. Submit templates for approval via Meta's Template Management API
2. Poll / handle webhook updates for approval status changes
3. Delete templates from Meta
4. Sync local template status with Meta's records

Meta Template Management API:
  POST   /<WABA_ID>/message_templates            → Create template
  GET    /<WABA_ID>/message_templates             → List templates
  GET    /<WABA_ID>/message_templates?name=<name> → Get specific template
  DELETE /<WABA_ID>/message_templates?name=<name> → Delete template

Webhook event:
  "message_template_status_update" → template approved/rejected/paused

Reference: https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# Meta API base
META_GRAPH_API = "https://graph.facebook.com/v21.0"


def _get_waba_id() -> str:
    """Get WhatsApp Business Account ID from env."""
    return os.environ.get("WA_BUSINESS_ACCOUNT_ID", "")


def _get_access_token() -> str:
    """Get WhatsApp API access token."""
    return os.environ.get("WA_ACCESS_TOKEN", "")


def is_meta_configured() -> bool:
    """Check if Meta template API credentials are configured."""
    return bool(_get_waba_id() and _get_access_token())


# ---------------------------------------------------------------------------
# Template submission to Meta
# ---------------------------------------------------------------------------

def _build_meta_template_payload(template: dict) -> dict:
    """
    Convert a Nazar template dict to Meta's Template Management API format.

    Meta API format:
    {
        "name": "template_name",
        "language": "en",
        "category": "UTILITY",
        "components": [
            {"type": "HEADER", "format": "TEXT", "text": "Hello"},
            {"type": "BODY", "text": "Hi {{1}}, ..."},
            {"type": "FOOTER", "text": "Reply STOP..."},
            {"type": "BUTTONS", "buttons": [...]}
        ]
    }
    """
    components = []

    # Header
    header = template.get("header") or {}
    header_type = header.get("type", "none")
    if header_type != "none":
        header_component = {"type": "HEADER"}
        if header_type == "text":
            header_component["format"] = "TEXT"
            header_component["text"] = header.get("text", "")
        elif header_type == "image":
            header_component["format"] = "IMAGE"
            # For template creation, Meta needs an example image handle
            # During sending, the actual image URL is passed in components
            example_url = header.get("image_url") or header.get("url", "")
            if example_url:
                header_component["example"] = {"header_handle": [example_url]}
        elif header_type == "video":
            header_component["format"] = "VIDEO"
        elif header_type == "document":
            header_component["format"] = "DOCUMENT"
        components.append(header_component)

    # Body (required)
    body_text = template.get("body", "")
    body_component = {"type": "BODY", "text": body_text}

    # Add example values for body variables
    variables = template.get("variables", [])
    if variables:
        example_values = {
            "name": "John",
            "company": "Acme Corp",
            "phone": "+919876543210",
            "topic": "our product",
            "deal_value": "₹50,000",
            "stage": "Qualified",
        }
        examples = [example_values.get(v, f"example_{v}") for v in variables]
        body_component["example"] = {"body_text": [examples]}
    components.append(body_component)

    # Footer
    footer = template.get("footer", "")
    if footer:
        components.append({"type": "FOOTER", "text": footer})

    # Buttons
    buttons = template.get("buttons", [])
    if buttons:
        meta_buttons = []
        for btn in buttons:
            btn_type = btn.get("type", "quick_reply")
            if btn_type == "quick_reply":
                meta_buttons.append({
                    "type": "QUICK_REPLY",
                    "text": btn.get("text", ""),
                })
            elif btn_type == "url":
                meta_buttons.append({
                    "type": "URL",
                    "text": btn.get("text", ""),
                    "url": btn.get("url", ""),
                })
            elif btn_type == "phone":
                meta_buttons.append({
                    "type": "PHONE_NUMBER",
                    "text": btn.get("text", ""),
                    "phone_number": btn.get("phone", ""),
                })
        if meta_buttons:
            components.append({"type": "BUTTONS", "buttons": meta_buttons})

    # Category must be uppercase for Meta API
    category = (template.get("category", "utility") or "utility").upper()
    # Meta uses MARKETING, UTILITY, AUTHENTICATION
    if category not in ("MARKETING", "UTILITY", "AUTHENTICATION"):
        category = "UTILITY"

    return {
        "name": template.get("name", ""),
        "language": template.get("language", "en"),
        "category": category,
        "components": components,
    }


async def submit_template_to_meta(template: dict) -> dict:
    """
    Submit a template to Meta's Template Management API for approval.

    Args:
        template: Nazar template dict from template_manager

    Returns:
        dict with:
          - success: bool
          - meta_id: str (Meta's template ID) if success
          - status: str ("PENDING", "APPROVED", etc.)
          - error: str if failed
    """
    waba_id = _get_waba_id()
    access_token = _get_access_token()

    if not waba_id or not access_token:
        return {
            "success": False,
            "error": "Meta API not configured. Set WA_BUSINESS_ACCOUNT_ID and WA_ACCESS_TOKEN in .env",
            "meta_id": None,
            "status": "not_configured",
        }

    url = f"{META_GRAPH_API}/{waba_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = _build_meta_template_payload(template)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                result = await resp.json()

                if resp.status == 200:
                    meta_id = result.get("id", "")
                    status = result.get("status", "PENDING")
                    logger.info(
                        "Template '%s' submitted to Meta (id=%s, status=%s)",
                        template.get("name"), meta_id, status,
                    )
                    return {
                        "success": True,
                        "meta_id": meta_id,
                        "status": status.lower(),
                        "error": None,
                    }
                else:
                    error_msg = result.get("error", {}).get("message", str(result))
                    error_code = result.get("error", {}).get("code", 0)
                    logger.error(
                        "Template '%s' submission failed: [%s] %s",
                        template.get("name"), error_code, error_msg,
                    )
                    return {
                        "success": False,
                        "meta_id": None,
                        "status": "failed",
                        "error": error_msg,
                        "error_code": error_code,
                    }
    except Exception as e:
        logger.error("Template submission request failed: %s", e)
        return {
            "success": False,
            "meta_id": None,
            "status": "error",
            "error": str(e),
        }


async def get_meta_template_status(template_name: str) -> Optional[dict]:
    """
    Fetch a template's current status from Meta's API.

    Returns:
        dict with status, id, category, etc., or None if not found.
    """
    waba_id = _get_waba_id()
    access_token = _get_access_token()

    if not waba_id or not access_token:
        return None

    url = f"{META_GRAPH_API}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"name": template_name}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                result = await resp.json()
                data = result.get("data", [])
                if data:
                    meta_tpl = data[0]
                    return {
                        "meta_id": meta_tpl.get("id", ""),
                        "name": meta_tpl.get("name", ""),
                        "status": meta_tpl.get("status", "").lower(),
                        "category": meta_tpl.get("category", ""),
                        "language": meta_tpl.get("language", ""),
                    }
                return None
    except Exception as e:
        logger.error("Failed to fetch template status from Meta: %s", e)
        return None


async def delete_template_from_meta(template_name: str) -> dict:
    """
    Delete a template from Meta's platform.

    Returns:
        dict with success: bool
    """
    waba_id = _get_waba_id()
    access_token = _get_access_token()

    if not waba_id or not access_token:
        return {"success": False, "error": "Meta API not configured"}

    url = f"{META_GRAPH_API}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"name": template_name}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers, params=params) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("success"):
                    logger.info("Template '%s' deleted from Meta", template_name)
                    return {"success": True}
                else:
                    error_msg = result.get("error", {}).get("message", str(result))
                    return {"success": False, "error": error_msg}
    except Exception as e:
        logger.error("Failed to delete template from Meta: %s", e)
        return {"success": False, "error": str(e)}


async def sync_all_templates() -> dict:
    """
    Sync all local templates with Meta's API status.

    Fetches all templates from Meta and updates local approval_status.

    Returns:
        dict with synced_count, updated_count, errors
    """
    from template_manager import list_templates, update_template

    waba_id = _get_waba_id()
    access_token = _get_access_token()

    if not waba_id or not access_token:
        return {"synced": 0, "updated": 0, "error": "Meta API not configured"}

    url = f"{META_GRAPH_API}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                result = await resp.json()
                meta_templates = result.get("data", [])
    except Exception as e:
        return {"synced": 0, "updated": 0, "error": str(e)}

    # Build lookup: name → status
    meta_status_map = {}
    for mt in meta_templates:
        name = mt.get("name", "")
        status = mt.get("status", "").lower()
        # Map Meta statuses to our statuses
        status_map = {
            "approved": "approved",
            "pending": "pending",
            "rejected": "rejected",
            "paused": "rejected",  # Paused templates can't be sent
            "disabled": "rejected",
        }
        meta_status_map[name] = status_map.get(status, status)

    # Update local templates
    local_templates = list_templates()
    updated = 0
    for tpl in local_templates:
        name = tpl.get("name", "")
        if name in meta_status_map:
            new_status = meta_status_map[name]
            if tpl.get("approval_status") != new_status:
                update_template(tpl["id"], approval_status=new_status)
                updated += 1
                logger.info(
                    "Template '%s' status synced: %s → %s",
                    name, tpl.get("approval_status"), new_status,
                )

    return {
        "synced": len(meta_templates),
        "updated": updated,
        "local_count": len(local_templates),
        "error": None,
    }


def handle_template_status_webhook(payload: dict) -> dict:
    """
    Handle a Meta webhook for template status changes.

    Webhook event type: "message_template_status_update"

    Payload structure:
    {
        "event": "APPROVED" | "REJECTED" | "PENDING_DELETION" | "DISABLED" | "PAUSED",
        "message_template_id": 123456,
        "message_template_name": "template_name",
        "message_template_language": "en",
        "reason": "..." (if rejected)
    }
    """
    from template_manager import get_template_by_name, update_template

    event = payload.get("event", "").upper()
    template_name = payload.get("message_template_name", "")
    reason = payload.get("reason", "")

    if not template_name:
        return {"handled": False, "error": "No template name in webhook payload"}

    # Map Meta events to our statuses
    event_status_map = {
        "APPROVED": "approved",
        "REJECTED": "rejected",
        "PENDING_DELETION": "rejected",
        "DISABLED": "rejected",
        "PAUSED": "rejected",
        "REINSTATED": "approved",
        "FLAGGED": "pending",
    }

    new_status = event_status_map.get(event, "pending")

    # Find and update local template
    local_tpl = get_template_by_name(template_name)
    if not local_tpl:
        logger.warning(
            "Template status webhook for unknown template: %s (event=%s)",
            template_name, event,
        )
        return {"handled": False, "error": f"Template '{template_name}' not found locally"}

    old_status = local_tpl.get("approval_status", "pending")
    update_fields = {"approval_status": new_status}
    if reason:
        update_fields["rejection_reason"] = reason

    update_template(local_tpl["id"], **update_fields)

    logger.info(
        "Template '%s' status updated via webhook: %s → %s (event=%s, reason=%s)",
        template_name, old_status, new_status, event, reason or "none",
    )

    return {
        "handled": True,
        "template_name": template_name,
        "old_status": old_status,
        "new_status": new_status,
        "event": event,
        "reason": reason,
    }
