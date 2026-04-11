"""
Nazar — WhatsApp Sales Intelligence Platform

FastAPI server that:
1. Receives webhooks from WhatsApp Cloud API
2. Routes inbound messages to the AI conversation engine
3. Sends responses back via Cloud API
4. Serves the REST API for the dashboard
5. Serves the frontend (single HTML file)
"""

import os
import re
import ssl
# Fix OpenBLAS thread limit issue in constrained environments
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import asyncio
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import aiohttp
try:
    import certifi
except Exception:
    certifi = None
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

# Add core to path
APP_DIR = Path(__file__).parent
load_dotenv(APP_DIR / ".env")
sys.path.insert(0, str(APP_DIR / "core"))

from db import get_storage_backend_name, init_db
from auth_store import create_session, get_default_owner_context, get_session, revoke_session, role_allowed
from audit_store import list_audit_events, record_audit_event
from analytics_store import get_operational_metrics
from contact_manager import (
    create_contact, get_contact, update_contact, delete_contact,
    list_contacts, get_contact_by_phone, move_stage, update_lead_score,
    add_tag, remove_tag, save_message, get_today_conversation,
    get_conversation_history, import_contacts_csv, get_pipeline_summary,
    get_conversation_record, list_conversation_records, set_conversation_bot_mode,
    get_conversation_bot_mode, mark_conversation_handoff_required, assign_conversation,
    set_conversation_ai_assist, set_conversation_use_case,
    update_message_status_by_wa_id, set_conversation_status, get_conversation_metrics,
    list_contact_notes, add_contact_note,
    initialize_storage,
    contact_exists, PIPELINE_STAGES,
)
from customer_memory import (
    get_relevant_context, add_message as memory_add_message,
    extract_signals_from_message, add_signal, get_customer_summary,
    search as memory_search, delete_customer_vectors,
)
from conversation import generate_ai_reply, get_or_create_contact_for_phone
from llm_router import call_llm_safe, get_health_status as llm_health
from transcription import transcribe_audio, TranscriptionError
from outbound import (
    execute_broadcast, log_broadcast, get_broadcast_history,
    get_broadcast_stats, personalize_message, generate_followup_context,
)
from template_manager import (
    list_templates, get_template, get_template_by_name, create_template,
    update_template, delete_template, increment_usage, render_template,
    suggest_template, get_template_stats, TEMPLATE_CATEGORIES,
)
from digest_engine import (
    get_followup_queue, generate_daily_digest, format_digest_for_whatsapp,
    save_digest, get_digest_history,
)
from job_queue import enqueue_job, get_job, list_jobs
from policy_store import (
    get_reply_policy,
    get_routing_rule,
    initialize_reply_policies,
    list_reply_policies,
    list_routing_rules,
    resolve_policy_for_context,
    resolve_reply_policy,
    upsert_reply_policy,
    upsert_routing_rule,
)
from simulator import SIMULATOR_SCENARIOS, simulate_broadcast_run_async, simulate_inbound_event_async
from telegram_adapter import (
    send_telegram_message,
    telegram_bot_token,
    telegram_bot_username,
    telegram_chat_id,
    telegram_ready,
)
from workspace_store import get_membership_by_user_id, get_workspace_config, initialize_workspace_store, list_team_members, update_workspace_config

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# --- Config ---
ENV_WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
ENV_WHATSAPP_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
ENV_WHATSAPP_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "nazar_verify_2026")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Nazar", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track processed messages to avoid duplicates
_processed_messages: deque = deque(maxlen=10000)

@app.on_event("startup")
async def startup_event():
    init_db()
    initialize_storage()
    initialize_workspace_store()
    initialize_reply_policies()
    logger.info(f"CRM storage ready ({get_storage_backend_name()})")


def _log_task_error(task: asyncio.Task):
    """Callback to log unhandled exceptions from fire-and-forget tasks."""
    if not task.cancelled() and task.exception():
        logger.error(f"Background task failed: {task.exception()}", exc_info=task.exception())


def _whatsapp_config() -> dict:
    config = get_workspace_config()
    phone_number_id = (
        config.get("whatsapp_phone_number_id")
        or config.get("wa_phone_number_id")
        or ENV_WHATSAPP_PHONE_NUMBER_ID
        or ""
    ).strip()
    access_token = (
        config.get("whatsapp_access_token")
        or config.get("wa_access_token")
        or ENV_WHATSAPP_ACCESS_TOKEN
        or ""
    ).strip()
    verify_token = (
        config.get("whatsapp_verify_token")
        or config.get("wa_verify_token")
        or ENV_WHATSAPP_VERIFY_TOKEN
        or "nazar_verify_2026"
    ).strip()
    test_number = (
        config.get("whatsapp_test_number")
        or config.get("wa_test_number")
        or ""
    ).strip()
    return {
        "phone_number_id": phone_number_id,
        "access_token": access_token,
        "verify_token": verify_token,
        "test_number": test_number,
        "api_url": f"https://graph.facebook.com/v21.0/{phone_number_id}/messages" if phone_number_id else "",
    }


def _whatsapp_ready() -> bool:
    config = _whatsapp_config()
    return bool(config["phone_number_id"] and config["access_token"])


def _mask_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "•" * len(raw)
    return f"{raw[:4]}…{raw[-4:]}"


def _contact_channel(contact: dict) -> str:
    return (contact.get("channel") or ("telegram" if str(contact.get("phone") or "").startswith("telegram:") else "whatsapp")).strip()


def _extract_provider_message_id(response: dict) -> str:
    if "messages" in response:
        return ((response.get("messages") or [{}])[0]).get("id", "")
    result = response.get("result") or {}
    return str(result.get("message_id") or "")


def _tls_context():
    if certifi is None:
        return None
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


# ====================================================================
#  AUTH MIDDLEWARE
# ====================================================================

def _auth_context(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        session = get_session(token)
        if session:
            return session

    key = request.headers.get("X-Nazar-Key", "")
    expected_key = os.environ.get("NAZAR_API_KEY", "nazar_dev_key")
    if key == expected_key:
        owner_context = get_default_owner_context()
        if owner_context:
            return owner_context

    raise HTTPException(status_code=401, detail="Authentication required")


def _require_roles(request: Request, *roles: str) -> dict:
    context = _auth_context(request)
    actual_role = ((context.get("user") or {}).get("role") or "").strip().lower()
    if roles and not role_allowed(actual_role, set(roles)):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return context


def _check_api_key(request: Request):
    return _require_roles(request, "agent")


def _actor_user_id(request: Request) -> Optional[str]:
    context = _require_roles(request, "agent")
    user = context.get("user") or {}
    return user.get("id")


def _slugify_policy_key(value: str, fallback: str = "campaign") -> str:
    raw = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return normalized or fallback


def _campaign_reply_policy(campaign_key: str, reply_mode: Optional[str], human_queue: Optional[str]) -> Optional[dict]:
    selected_mode = (reply_mode or "").strip().lower()
    if not selected_mode:
        return None
    policy_key = f"campaign_{_slugify_policy_key(campaign_key, 'reply_flow')}"
    default_policy = resolve_reply_policy("default_inbound")
    return upsert_reply_policy(
        policy_key,
        {
            "display_name": f"Campaign: {campaign_key}",
            "description": f"Reply handling for campaign {campaign_key}.",
            "reply_mode": selected_mode,
            "fallback_queue": (human_queue or default_policy.get("fallback_queue") or "sales").strip() or "sales",
            "force_human_keywords": default_policy.get("force_human_keywords") or [],
            "active": True,
        },
    )


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    body = await request.json()
    api_key = body.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key is required")
    try:
        return create_session(api_key)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else ""
    revoked = revoke_session(token)
    return {"ok": revoked}


@app.get("/api/auth/me")
async def api_auth_me(request: Request):
    return _auth_context(request)


# ====================================================================
#  WHATSAPP CLOUD API HELPERS
# ====================================================================

async def send_whatsapp_message(phone: str, text: str) -> dict:
    """Send a text message via WhatsApp Cloud API."""
    config = _whatsapp_config()
    if not (config["phone_number_id"] and config["access_token"]):
        raise HTTPException(503, "WhatsApp is not configured")
    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace("+", ""),
        "type": "text",
        "text": {"body": text},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config["api_url"],
                headers=headers,
                json=payload,
                ssl=_tls_context(),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    logger.error(f"WhatsApp send failed: {result}")
                    detail = result.get("error", {}).get("message") or result
                    raise HTTPException(resp.status, f"WhatsApp send failed: {detail}")
                return result
    except aiohttp.ClientConnectorCertificateError as exc:
        raise HTTPException(
            502,
            "WhatsApp send failed because this machine cannot verify Meta's SSL certificate. "
            "Install Python certificates or use a runtime with a valid CA bundle."
        ) from exc


async def send_template_message(phone: str, template_name: str, language: str = "en", components: list = None) -> dict:
    """Send a template message via WhatsApp Cloud API."""
    config = _whatsapp_config()
    if not (config["phone_number_id"] and config["access_token"]):
        raise HTTPException(503, "WhatsApp is not configured")
    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Content-Type": "application/json",
    }
    template_obj = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template_obj["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace("+", ""),
        "type": "template",
        "template": template_obj,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config["api_url"],
                headers=headers,
                json=payload,
                ssl=_tls_context(),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    logger.error(f"Template send failed: {result}")
                    detail = result.get("error", {}).get("message") or result
                    raise HTTPException(resp.status, f"Template send failed: {detail}")
                return result
    except aiohttp.ClientConnectorCertificateError as exc:
        raise HTTPException(
            502,
            "WhatsApp template send failed because this machine cannot verify Meta's SSL certificate. "
            "Install Python certificates or use a runtime with a valid CA bundle."
        ) from exc


async def send_contact_message(contact: dict, text: str) -> dict:
    channel = _contact_channel(contact)
    if channel == "telegram":
        return await send_telegram_message(contact["phone"], text)
    return await send_whatsapp_message(contact["phone"], text)


async def mark_as_read(message_id: str):
    """Mark a WhatsApp message as read."""
    config = _whatsapp_config()
    if not (config["phone_number_id"] and config["access_token"]):
        return
    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            config["api_url"],
            headers=headers,
            json=payload,
            ssl=_tls_context(),
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                logger.error(f"Mark read failed for {message_id}: {err}")


async def download_whatsapp_media(media_id: str) -> tuple:
    """Download media from WhatsApp Cloud API. Returns (bytes, mime_type)."""
    config = _whatsapp_config()
    if not config["access_token"]:
        raise Exception("WhatsApp is not configured")
    headers = {"Authorization": f"Bearer {config['access_token']}"}
    async with aiohttp.ClientSession() as session:
        meta_url = f"https://graph.facebook.com/v21.0/{media_id}"
        async with session.get(meta_url, headers=headers, ssl=_tls_context()) as resp:
            if resp.status != 200:
                raise Exception(f"Media metadata fetch failed: {resp.status}")
            meta = await resp.json()

        download_url = meta.get("url", "")
        mime_type = meta.get("mime_type", "audio/ogg")

        async with session.get(download_url, headers=headers, ssl=_tls_context()) as resp:
            if resp.status != 200:
                raise Exception(f"Media download failed: {resp.status}")
            data = await resp.read()
            return (data, mime_type)


# ====================================================================
#  WHATSAPP WEBHOOK
# ====================================================================

@app.get("/webhook")
async def webhook_verify(request: Request):
    """WhatsApp webhook verification (GET)."""
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == _whatsapp_config()["verify_token"]:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def webhook_receive(request: Request):
    """WhatsApp webhook — receive inbound messages."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=200)

    entries = body.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            statuses = value.get("statuses", [])

            # Handle status updates (delivered, read)
            for status in statuses:
                _handle_status_update(status)

            for msg in messages:
                msg_id = msg.get("id", "")
                if msg_id in _processed_messages:
                    continue
                _processed_messages.append(msg_id)

                phone = msg.get("from", "")
                msg_type = msg.get("type", "")

                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                    if text:
                        t1 = asyncio.create_task(mark_as_read(msg_id))
                        t1.add_done_callback(_log_task_error)
                        try:
                            queued = _queue_saved_inbound_text(phone, text, msg_id)
                            logger.info(f"[{phone}] Inbound text queued: {queued}")
                        except Exception as exc:
                            logger.error(f"Failed to queue inbound text for {phone}: {exc}", exc_info=True)

                elif msg_type == "audio":
                    media_id = msg.get("audio", {}).get("id", "")
                    if media_id:
                        t1 = asyncio.create_task(mark_as_read(msg_id))
                        t1.add_done_callback(_log_task_error)
                        job = enqueue_job(
                            "process_inbound_voice",
                            {
                                "phone": f"+{phone}" if not phone.startswith("+") else phone,
                                "media_id": media_id,
                                "wa_message_id": msg_id,
                            },
                        )
                        logger.info(f"[{phone}] Inbound voice queued: {job['id']}")

    return Response(status_code=200)


def _handle_status_update(status: dict):
    """Handle WhatsApp delivery/read status updates."""
    wa_msg_id = status.get("id", "")
    new_status = status.get("status", "")  # sent, delivered, read, failed
    recipient = status.get("recipient_id", "")

    if wa_msg_id and new_status:
        logger.info(f"Status update: {wa_msg_id} → {new_status} for {recipient}")
        update_message_status_by_wa_id(wa_msg_id, new_status, recipient=recipient)


def _queue_saved_inbound_text(phone: str, text: str, wa_message_id: str) -> dict:
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    contact = get_or_create_contact_for_phone(phone_e164)
    conversation = get_conversation_record(contact["contact_id"])
    if conversation and not conversation.get("bot_mode", True):
        save_message(contact["contact_id"], "inbound", text, wa_message_id=wa_message_id)
        logger.info(f"[{phone}] Bot off — inbound message saved without AI reply")
        return {"queued": False, "reason": "bot_mode_off", "contact_id": contact["contact_id"]}

    inbound_record = save_message(contact["contact_id"], "inbound", text, wa_message_id=wa_message_id)
    job = enqueue_job(
        "process_saved_inbound_text",
        {
            "contact_id": contact["contact_id"],
            "conversation_id": inbound_record["conversation_id"],
            "phone": phone_e164,
            "message": text,
            "wa_message_id": wa_message_id,
        },
    )
    return {
        "queued": True,
        "job": job,
        "contact_id": contact["contact_id"],
        "conversation_id": inbound_record["conversation_id"],
    }


# ====================================================================
#  DASHBOARD API — OVERVIEW
# ====================================================================

@app.get("/api/overview")
async def api_overview(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    inbox_metrics = get_conversation_metrics()
    operations = get_operational_metrics(days=30)

    # Calculate stats
    active_leads = len([c for c in contacts if c["pipeline_stage"] not in ("Won", "Lost")])
    total_revenue = sum((c.get("deal_value") or 0) for c in contacts if c.get("pipeline_stage") == "Won")
    pipeline_value = sum((c.get("deal_value") or 0) for c in contacts if c.get("pipeline_stage") not in ("Won", "Lost"))

    # Recent activity (last 24h contacts with messages)
    recent_contacts = sorted(contacts, key=lambda c: c.get("last_replied_at") or c.get("created_at") or "", reverse=True)[:10]

    return {
        "stats": {
            "active_leads": active_leads,
            "total_contacts": len(contacts),
            "pipeline_value": pipeline_value,
            "total_revenue": total_revenue,
            "bot_conversations_today": 0,
            "needs_reply": inbox_metrics["needs_reply"],
            "unassigned_conversations": inbox_metrics["unassigned_conversations"],
            "avg_response_seconds": inbox_metrics["avg_response_seconds"],
        },
        "pipeline": pipeline,
        "inbox_metrics": inbox_metrics,
        "operations": operations,
        "recent_contacts": [
            {
                "contact_id": c["contact_id"],
                "name": c.get("name", "Unknown"),
                "phone": c.get("phone", ""),
                "stage": c.get("pipeline_stage", "New"),
                "deal_value": c.get("deal_value", 0),
                "last_replied_at": c.get("last_replied_at", ""),
            }
            for c in recent_contacts
        ],
    }


@app.get("/api/activity")
async def api_activity(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    activities = []
    for c in contacts:
        if c.get("last_replied_at"):
            activities.append({
                "type": "message",
                "contact_id": c["contact_id"],
                "contact_name": c.get("name", "Unknown"),
                "time": c["last_replied_at"],
                "detail": f"Last activity in {c['pipeline_stage']} stage",
            })
    activities.sort(key=lambda a: a["time"], reverse=True)
    return {"activities": activities[:20]}


# ====================================================================
#  DASHBOARD API — CONTACTS
# ====================================================================

@app.get("/api/contacts")
async def api_list_contacts(request: Request, stage: str = None, tag: str = None, assigned_to: str = None):
    _require_roles(request, "agent")
    contacts = list_contacts(stage=stage, tag=tag, assigned_to=assigned_to)
    return {"contacts": contacts, "total": len(contacts)}


@app.post("/api/contacts")
async def api_create_contact(request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    name = body.get("name", "")
    phone = body.get("phone", "")
    if not phone:
        raise HTTPException(400, "phone is required")
    try:
        contact = create_contact(
            name=name,
            phone=phone,
            company=body.get("company"),
            source=body.get("source"),
            assigned_to=body.get("assigned_to"),
            tags=body.get("tags"),
        )
        # Set deal_value if provided (create_contact doesn't accept it directly)
        deal_value = body.get("deal_value")
        if deal_value:
            contact = update_contact(contact["contact_id"], deal_value=float(deal_value))
        record_audit_event(
            "contact",
            contact["contact_id"],
            "created",
            {"name": contact.get("name"), "phone": contact.get("phone")},
            actor_user_id=_actor_user_id(request),
        )
        return {"contact": contact}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/contacts/{contact_id}")
async def api_get_contact(contact_id: str, request: Request):
    _require_roles(request, "agent")
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    return {"contact": contact}


@app.patch("/api/contacts/{contact_id}")
async def api_update_contact(contact_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    try:
        contact = update_contact(contact_id, **body)
        record_audit_event(
            "contact",
            contact_id,
            "updated",
            {"fields": sorted(body.keys())},
            actor_user_id=_actor_user_id(request),
        )
        return {"contact": contact}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/contacts/{contact_id}")
async def api_delete_contact(contact_id: str, request: Request):
    _require_roles(request, "agent")
    try:
        delete_contact(contact_id)
        delete_customer_vectors(contact_id)
        record_audit_event(
            "contact",
            contact_id,
            "deleted",
            {},
            actor_user_id=_actor_user_id(request),
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/contacts/import")
async def api_import_contacts(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    csv_content = body.get("csv", "")
    if not csv_content:
        raise HTTPException(400, "csv content is required")
    result = import_contacts_csv(csv_content)
    return result


# ====================================================================
#  DASHBOARD API — CONVERSATIONS
# ====================================================================

@app.get("/api/conversations")
async def api_list_conversations(
    request: Request,
    status: str = None,
    assigned_user_id: str = None,
    unassigned: bool = False,
    human_required: bool = False,
    needs_reply: bool = False,
    assigned_to_me: bool = False,
    queue: str = None,
    source_type: str = None,
    ai_assist: bool = False,
):
    context = _require_roles(request, "agent")
    active_assigned_user_id = assigned_user_id
    if assigned_to_me:
        active_assigned_user_id = (context.get("user") or {}).get("id")
    return {
        "conversations": list_conversation_records(
            status=status,
            assigned_user_id=active_assigned_user_id,
            only_unassigned=unassigned,
            only_human_required=human_required,
            only_needs_reply=needs_reply,
            queue=queue,
            source_type=source_type,
            require_ai_assist=ai_assist,
        )
    }


@app.get("/api/conversations/{conversation_id}")
async def api_get_conversation(conversation_id: str, request: Request, days: int = 7):
    _require_roles(request, "agent")
    conversation = get_conversation_record(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    contact = get_contact(conversation["contact_id"])
    if not contact:
        raise HTTPException(404, "Contact not found")
    messages = get_conversation_history(conversation_id, days=days)
    memory_summary = get_customer_summary(contact["contact_id"])
    return {
        "contact": contact,
        "conversation": conversation,
        "messages": messages,
        "memory": memory_summary,
        "bot_mode": conversation.get("bot_mode", True) if conversation else True,
    }


@app.post("/api/conversations/{conversation_id}/send")
async def api_send_message(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    text = body.get("message", "")
    if not text:
        raise HTTPException(400, "message is required")

    conversation = get_conversation_record(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    contact = get_contact(conversation["contact_id"])
    if not contact:
        raise HTTPException(404, "Contact not found")

    result = await send_contact_message(contact, text)

    # Save to conversation history
    wa_msg_id = _extract_provider_message_id(result)

    save_message(conversation["conversation_id"], "outbound", text, sent_by="human", wa_message_id=wa_msg_id)
    memory_add_message(contact["contact_id"], "outbound", text)

    # Update contact
    update_contact(contact["contact_id"], last_contacted_at=datetime.now(IST).isoformat())
    record_audit_event(
        "conversation",
        conversation["conversation_id"],
        "message_sent",
        {"wa_message_id": wa_msg_id, "length": len(text)},
        actor_user_id=_actor_user_id(request),
    )

    return {"ok": True, "wa_message_id": wa_msg_id}


@app.post("/api/conversations/{conversation_id}/handover")
async def api_handover(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    bot_on = body.get("bot_mode", True)
    try:
        conversation = set_conversation_bot_mode(conversation_id, bot_on)
        logger.info(f"Bot mode for {conversation['conversation_id']}: {'ON' if bot_on else 'OFF'}")
        record_audit_event(
            "conversation",
            conversation["conversation_id"],
            "bot_mode_changed",
            {"bot_mode": conversation["bot_mode"]},
            actor_user_id=_actor_user_id(request),
        )
        return {"bot_mode": conversation["bot_mode"], "conversation": conversation}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/conversations/{conversation_id}/assign")
async def api_assign_conversation(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    user_id = body.get("user_id")
    if user_id is None:
        user_id = body.get("assigned_user_id")
    if body.get("assign_to_me"):
        user_id = _actor_user_id(request)
    try:
        conversation = assign_conversation(conversation_id, user_id)
        record_audit_event(
            "conversation",
            conversation["conversation_id"],
            "assigned",
            {"assigned_user_id": user_id},
            actor_user_id=_actor_user_id(request),
        )
        return {"conversation": conversation}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/conversations/{conversation_id}/status")
async def api_update_conversation_status(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    status = body.get("status", "")
    try:
        conversation = set_conversation_status(conversation_id, status)
        record_audit_event(
            "conversation",
            conversation["conversation_id"],
            "status_changed",
            {"status": status},
            actor_user_id=_actor_user_id(request),
        )
        return {"conversation": conversation}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/conversations/{conversation_id}/use-case")
async def api_update_conversation_use_case(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    use_case_key = (body.get("use_case_key") or body.get("policy_use_case_key") or "").strip()
    if not use_case_key:
        raise HTTPException(400, "use_case_key is required")
    conversation = get_conversation_record(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    policy = resolve_reply_policy(use_case_key)
    try:
        updated = set_conversation_use_case(
            conversation_id,
            use_case_key=policy["use_case_key"],
            source_type=body.get("source_type") or "conversation_override",
            source_ref=body.get("source_ref") or conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        record_audit_event(
            "conversation",
            conversation_id,
            "use_case_changed",
            {"use_case_key": policy["use_case_key"], "reply_mode": policy["reply_mode"]},
            actor_user_id=_actor_user_id(request),
        )
        return {"conversation": updated, "policy": policy}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


# ====================================================================
#  DASHBOARD API — MEMORY
# ====================================================================

@app.get("/api/contacts/{contact_id}/memory")
async def api_contact_memory(contact_id: str, request: Request, query: str = ""):
    _require_roles(request, "agent")
    summary = get_customer_summary(contact_id)
    results = []
    if query:
        results = memory_search(contact_id, query, n_results=20)
    return {"summary": summary, "search_results": results}


@app.post("/api/conversations/{conversation_id}/ai-reply")
async def api_queue_ai_reply(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    prompt = (body.get("message") or "").strip()
    conversation = get_conversation_record(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    if not prompt:
        raise HTTPException(400, "message is required")
    job = enqueue_job(
        "ai_reply_suggestion",
        {"contact_id": conversation["contact_id"], "conversation_id": conversation_id, "message": prompt},
        requested_by_user_id=_actor_user_id(request),
    )
    record_audit_event(
        "conversation",
        conversation_id,
        "ai_reply_queued",
        {"job_id": job["id"]},
        actor_user_id=_actor_user_id(request),
    )
    return {"queued": True, "job": job}


@app.post("/api/conversations/{conversation_id}/ai-assist/send")
async def api_send_ai_assist(conversation_id: str, request: Request):
    _require_roles(request, "agent")
    conversation = get_conversation_record(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    contact = get_contact(conversation["contact_id"])
    if not contact:
        raise HTTPException(404, "Contact not found")
    body = await request.json()
    message = (body.get("message") or conversation.get("ai_assist_draft") or "").strip()
    if not message:
        raise HTTPException(400, "No AI assist draft available")
    result = await send_contact_message(contact, message)
    wa_msg_id = _extract_provider_message_id(result)
    save_message(conversation_id, "outbound", message, sent_by="human_ai_assist", wa_message_id=wa_msg_id)
    set_conversation_ai_assist(conversation_id, None, status=None)
    record_audit_event(
        "conversation",
        conversation_id,
        "ai_assist_sent",
        {"wa_message_id": wa_msg_id},
        actor_user_id=_actor_user_id(request),
    )
    return {"ok": True, "wa_message_id": wa_msg_id}


@app.post("/api/contacts/{contact_id}/followup-draft")
async def api_queue_followup_draft(contact_id: str, request: Request):
    _require_roles(request, "agent")
    if not get_contact(contact_id):
        raise HTTPException(404, "Contact not found")
    job = enqueue_job(
        "contact_followup_draft",
        {"contact_id": contact_id},
        requested_by_user_id=_actor_user_id(request),
    )
    record_audit_event(
        "contact",
        contact_id,
        "followup_draft_queued",
        {"job_id": job["id"]},
        actor_user_id=_actor_user_id(request),
    )
    return {"queued": True, "job": job}


@app.post("/api/contacts/{contact_id}/summary/refresh")
async def api_queue_contact_summary(contact_id: str, request: Request):
    _require_roles(request, "agent")
    if not get_contact(contact_id):
        raise HTTPException(404, "Contact not found")
    job = enqueue_job(
        "contact_summary_refresh",
        {"contact_id": contact_id},
        requested_by_user_id=_actor_user_id(request),
    )
    record_audit_event(
        "contact",
        contact_id,
        "summary_refresh_queued",
        {"job_id": job["id"]},
        actor_user_id=_actor_user_id(request),
    )
    return {"queued": True, "job": job}


@app.get("/api/contacts/{contact_id}/notes")
async def api_contact_notes(contact_id: str, request: Request):
    _require_roles(request, "agent")
    try:
        return {"notes": list_contact_notes(contact_id)}
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")


@app.post("/api/contacts/{contact_id}/notes")
async def api_add_contact_note(contact_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    note_body = body.get("body", "")
    try:
        note = add_contact_note(contact_id, note_body, author_user_id=_actor_user_id(request))
        record_audit_event(
            "contact",
            contact_id,
            "note_added",
            {"note_id": note["id"], "length": len(note["body"])},
            actor_user_id=_actor_user_id(request),
        )
        return {"note": note}
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ====================================================================
#  DASHBOARD API — PIPELINE
# ====================================================================

@app.get("/api/pipeline")
async def api_pipeline(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    pipeline = {}
    for stage in PIPELINE_STAGES:
        stage_contacts = [c for c in contacts if c.get("pipeline_stage") == stage]
        pipeline[stage] = {
            "contacts": stage_contacts,
            "count": len(stage_contacts),
            "total_value": sum(c.get("deal_value", 0) for c in stage_contacts),
        }
    return {"pipeline": pipeline, "stages": PIPELINE_STAGES}


@app.patch("/api/pipeline/{contact_id}/move")
async def api_move_stage(contact_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    new_stage = body.get("stage", "")
    try:
        contact = move_stage(contact_id, new_stage)
        record_audit_event(
            "contact",
            contact_id,
            "stage_changed",
            {"stage": new_stage},
            actor_user_id=_actor_user_id(request),
        )
        return {"contact": contact}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ====================================================================
#  DASHBOARD API — FOLLOW-UPS
# ====================================================================

@app.get("/api/followups")
async def api_followups(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    now = datetime.now(IST)
    followups = []

    for c in contacts:
        if c["pipeline_stage"] in ("Won", "Lost"):
            continue

        last_contact = c.get("last_contacted_at") or c.get("last_replied_at") or ""
        if not last_contact:
            continue

        try:
            last_dt = datetime.fromisoformat(last_contact)
            days_since = (now - last_dt).days
        except Exception:
            days_since = 999

        if days_since >= 2:  # Follow up if no contact in 2+ days
            priority = "high" if days_since >= 5 else "medium" if days_since >= 3 else "low"
            followups.append({
                "contact_id": c["contact_id"],
                "name": c.get("name", "Unknown"),
                "phone": c.get("phone", ""),
                "stage": c["pipeline_stage"],
                "deal_value": c.get("deal_value", 0),
                "days_since_contact": days_since,
                "priority": priority,
                "last_contacted_at": last_contact,
            })

    followups.sort(key=lambda f: f["days_since_contact"], reverse=True)
    return {"followups": followups}


# ====================================================================
#  DASHBOARD API — BROADCASTS
# ====================================================================

@app.post("/api/broadcasts")
@app.post("/api/campaigns")
async def api_broadcast(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    message = body.get("message", "")
    template_name = body.get("template", "")
    objective = (body.get("objective") or "").strip() or None
    filter_stage = body.get("stage")
    filter_tag = body.get("tag")
    contact_ids = body.get("contact_ids", [])
    campaign_key = (body.get("campaign_key") or "").strip() or "broadcast_reply"
    explicit_policy_key = (body.get("reply_use_case_key") or "").strip() or None
    direct_reply_mode = (body.get("reply_mode") or "").strip() or None
    direct_human_queue = (body.get("human_queue") or "").strip() or None
    custom_campaign_policy = _campaign_reply_policy(campaign_key, direct_reply_mode, direct_human_queue)
    if custom_campaign_policy:
        reply_policy = custom_campaign_policy
        routing = {"policy": reply_policy, "scope_type": "campaign", "scope_key": campaign_key, "reply_mode_source": "campaign_form"}
    else:
        routing = resolve_policy_for_context(
            pipeline_stage=filter_stage,
            campaign_key=campaign_key,
            explicit_policy_key=explicit_policy_key,
        )
        reply_policy = routing["policy"]

    if not message and not template_name:
        raise HTTPException(400, "message or template required")

    job = enqueue_job(
        "broadcast_send",
        {
            "message": message,
            "template": template_name,
            "objective": objective,
            "stage": filter_stage,
            "tag": filter_tag,
            "contact_ids": contact_ids,
            "campaign_key": campaign_key,
            "reply_use_case_key": reply_policy["use_case_key"],
        },
        requested_by_user_id=_actor_user_id(request),
    )
    record_audit_event(
        "broadcast",
        job["id"],
        "queued",
        {
            "kind": job["kind"],
            "contact_ids": len(contact_ids),
            "stage": filter_stage,
            "tag": filter_tag,
            "objective": objective,
            "campaign_key": campaign_key,
            "reply_use_case_key": reply_policy["use_case_key"],
            "resolved_scope_type": routing["scope_type"],
        },
        actor_user_id=_actor_user_id(request),
    )
    return {"queued": True, "job": job, "reply_policy": reply_policy, "routing": routing}


# ====================================================================
#  DASHBOARD API — PRODUCT SIMULATOR
# ====================================================================

@app.get("/api/simulate/scenarios")
async def api_list_simulator_scenarios(request: Request):
    _require_roles(request, "agent")
    return {"scenarios": SIMULATOR_SCENARIOS}


@app.post("/api/simulate/inbound")
async def api_simulate_inbound(request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    result = await simulate_inbound_event_async(
        scenario_key=(body.get("scenario_key") or "new_lead").strip(),
        message=(body.get("message") or "").strip() or None,
        name=(body.get("name") or "").strip() or None,
        phone=(body.get("phone") or "").strip() or None,
        company=(body.get("company") or "").strip() or None,
        pipeline_stage=(body.get("pipeline_stage") or "").strip() or None,
        source_type=(body.get("source_type") or "").strip() or None,
        source_ref=(body.get("source_ref") or "").strip() or None,
        explicit_policy_key=(body.get("use_case_key") or "").strip() or None,
        contact_id=(body.get("contact_id") or "").strip() or None,
    )
    record_audit_event(
        "simulation",
        result["conversation"]["conversation_id"],
        "inbound_simulated",
        {
            "scenario_key": result["scenario_key"],
            "action": result["action"],
            "policy_use_case_key": result["policy"]["use_case_key"],
        },
        actor_user_id=_actor_user_id(request),
    )
    return result


@app.post("/api/simulate/broadcast")
@app.post("/api/simulate/campaign")
async def api_simulate_broadcast(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    message = (body.get("message") or "").strip()
    template_name = (body.get("template") or "").strip()
    objective = (body.get("objective") or "").strip() or None
    if not message and not template_name:
        raise HTTPException(400, "message or template is required")
    campaign_key = (body.get("campaign_key") or "").strip() or "simulated_campaign"
    explicit_policy_key = (body.get("reply_use_case_key") or "").strip() or None
    direct_reply_mode = (body.get("reply_mode") or "").strip() or None
    direct_human_queue = (body.get("human_queue") or "").strip() or None
    custom_campaign_policy = _campaign_reply_policy(campaign_key, direct_reply_mode, direct_human_queue)
    result = await simulate_broadcast_run_async(
        message=message,
        template_name=template_name,
        objective=objective,
        target_stage=(body.get("stage") or "").strip() or None,
        target_count=body.get("target_count") or 5,
        campaign_key=campaign_key,
        reply_use_case_key=(custom_campaign_policy or {}).get("use_case_key") or explicit_policy_key,
        simulate_reply_count=body.get("simulate_reply_count") or 0,
    )
    record_audit_event(
        "simulation",
        result["campaign_key"],
        "broadcast_simulated",
        {
            "target_count": result["target_count"],
            "reply_count": result["simulate_reply_count"],
            "policy_use_case_key": result["policy"]["use_case_key"],
        },
        actor_user_id=_actor_user_id(request),
    )
    return result


# ====================================================================
#  DASHBOARD API — CONFIG
# ====================================================================

@app.get("/api/config")
async def api_get_config(request: Request):
    _require_roles(request, "admin", "owner")
    config = get_workspace_config()
    wa = _whatsapp_config()
    config["whatsapp_connected"] = _whatsapp_ready()
    config["whatsapp_phone_number_id"] = wa["phone_number_id"]
    config["whatsapp_verify_token"] = wa["verify_token"]
    config["whatsapp_test_number"] = wa["test_number"]
    config["whatsapp_access_token_present"] = bool(wa["access_token"])
    config["whatsapp_access_token_masked"] = _mask_secret(wa["access_token"])
    config["telegram_connected"] = telegram_ready()
    config["telegram_bot_username"] = telegram_bot_username()
    return config


@app.put("/api/config")
async def api_update_config(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    if "whatsapp_access_token" in body and not str(body.get("whatsapp_access_token") or "").strip():
        body.pop("whatsapp_access_token")
    updated = update_workspace_config(body)
    wa = _whatsapp_config()
    updated["whatsapp_connected"] = _whatsapp_ready()
    updated["whatsapp_phone_number_id"] = wa["phone_number_id"]
    updated["whatsapp_verify_token"] = wa["verify_token"]
    updated["whatsapp_test_number"] = wa["test_number"]
    updated["whatsapp_access_token_present"] = bool(wa["access_token"])
    updated["whatsapp_access_token_masked"] = _mask_secret(wa["access_token"])
    updated["telegram_connected"] = telegram_ready()
    updated["telegram_bot_username"] = telegram_bot_username()
    record_audit_event(
        "workspace",
        updated.get("business_name") or "default",
        "config_updated",
        {"fields": sorted(body.keys())},
        actor_user_id=_actor_user_id(request),
    )
    return updated


@app.get("/api/whatsapp/status")
async def api_whatsapp_status(request: Request):
    _require_roles(request, "admin", "owner")
    wa = _whatsapp_config()
    recent_jobs = list_jobs(limit=25)
    failed_jobs = [job for job in recent_jobs if job.get("status") == "failed"]
    queued_jobs = [job for job in recent_jobs if job.get("status") == "queued"]
    inbound_jobs = [job for job in recent_jobs if job.get("kind") in {"inbound_saved_text", "inbound_voice"}]
    return {
        "configured": _whatsapp_ready(),
        "webhook_url": f"{request.base_url}webhook",
        "phone_number_id": wa["phone_number_id"],
        "verify_token": wa["verify_token"],
        "test_number": wa["test_number"],
        "access_token_present": bool(wa["access_token"]),
        "access_token_masked": _mask_secret(wa["access_token"]),
        "llm": llm_health(),
        "queue": {
            "queued_jobs": len(queued_jobs),
            "failed_jobs": len(failed_jobs),
            "recent_inbound_jobs": len(inbound_jobs),
        },
    }


@app.get("/api/telegram/status")
async def api_telegram_status(request: Request):
    _require_roles(request, "admin", "owner")
    recent_jobs = list_jobs(limit=50)
    poll_jobs = [job for job in recent_jobs if job.get("kind") == "telegram_poll"]
    return {
        "configured": telegram_ready(),
        "bot_username": telegram_bot_username(),
        "recent_poll_jobs": len(poll_jobs),
    }


@app.post("/api/whatsapp/test-send")
async def api_whatsapp_test_send(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    phone = (body.get("phone") or _whatsapp_config()["test_number"] or "").strip()
    mode = (body.get("mode") or "template").strip().lower()
    if not phone:
        raise HTTPException(400, "test phone number is required")
    if mode == "text":
        text = (body.get("message") or "Hello from Nazar. This is a connection test.").strip()
        result = await send_whatsapp_message(phone, text)
        return {"ok": True, "mode": "text", "result": result}
    template_name = (body.get("template_name") or "hello_world").strip()
    result = await send_template_message(phone, template_name)
    return {"ok": True, "mode": "template", "template_name": template_name, "result": result}


# ====================================================================
#  DASHBOARD API — KNOWLEDGE BASE
# ====================================================================

@app.post("/api/kb/upload")
async def api_upload_kb(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")

    kb_path = DATA_DIR / "knowledge_base.txt"
    kb_path.write_text(content, encoding="utf-8")
    logger.info(f"Knowledge base updated: {len(content)} chars")
    return {"ok": True, "length": len(content)}


@app.get("/api/kb")
async def api_get_kb(request: Request):
    _require_roles(request, "admin", "owner")
    kb_path = DATA_DIR / "knowledge_base.txt"
    if kb_path.exists():
        content = kb_path.read_text(encoding="utf-8")
        return {"content": content, "length": len(content)}
    return {"content": "", "length": 0}


# ====================================================================
#  DASHBOARD API — TEAM (stub for MVP)
# ====================================================================

@app.get("/api/team")
async def api_team(request: Request):
    _require_roles(request, "agent")
    return {"team": list_team_members()}


@app.get("/api/reply-policies")
async def api_list_reply_policies(request: Request):
    _require_roles(request, "agent")
    return {"policies": list_reply_policies()}


@app.get("/api/reply-policies/{use_case_key}")
async def api_get_reply_policy(use_case_key: str, request: Request):
    _require_roles(request, "agent")
    policy = get_reply_policy(use_case_key)
    if not policy:
        raise HTTPException(404, "Reply policy not found")
    return {"policy": policy}


@app.put("/api/reply-policies/{use_case_key}")
async def api_upsert_reply_policy(use_case_key: str, request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    policy = upsert_reply_policy(use_case_key, body)
    record_audit_event(
        "reply_policy",
        use_case_key,
        "updated",
        {"reply_mode": policy["reply_mode"], "fallback_queue": policy["fallback_queue"]},
        actor_user_id=_actor_user_id(request),
    )
    return {"policy": policy}


@app.get("/api/routing-rules")
async def api_list_routing_rules(request: Request, scope_type: str = None):
    _require_roles(request, "agent")
    return {"rules": list_routing_rules(scope_type=scope_type)}


@app.get("/api/routing-rules/{scope_type}/{scope_key}")
async def api_get_routing_rule(scope_type: str, scope_key: str, request: Request):
    _require_roles(request, "agent")
    rule = get_routing_rule(scope_type, scope_key)
    if not rule:
        raise HTTPException(404, "Routing rule not found")
    return {"rule": rule}


@app.put("/api/routing-rules/{scope_type}/{scope_key}")
async def api_upsert_routing_rule(scope_type: str, scope_key: str, request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    rule = upsert_routing_rule(scope_type, scope_key, body)
    record_audit_event(
        "routing_rule",
        f"{scope_type}:{scope_key}",
        "updated",
        {"policy_use_case_key": rule["policy_use_case_key"]},
        actor_user_id=_actor_user_id(request),
    )
    return {"rule": rule}




# ====================================================================
#  DASHBOARD API — TEMPLATES
# ====================================================================

@app.get("/api/templates")
async def api_list_templates(request: Request, category: str = None, status: str = None):
    _require_roles(request, "agent")
    templates = list_templates(category=category, status=status)
    stats = get_template_stats()
    return {"templates": templates, "stats": stats}


@app.get("/api/templates/{template_id}")
async def api_get_template(template_id: str, request: Request):
    _require_roles(request, "agent")
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return {"template": template}


@app.post("/api/templates")
async def api_create_template(request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    try:
        template = create_template(
            name=body.get("name", ""),
            body=body.get("body", ""),
            category=body.get("category", "utility"),
            variables=body.get("variables", []),
            language=body.get("language", "en"),
            description=body.get("description", ""),
        )
        record_audit_event(
            "template",
            template["id"],
            "created",
            {"name": template["name"]},
            actor_user_id=_actor_user_id(request),
        )
        return {"template": template}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/templates/{template_id}")
async def api_update_template(template_id: str, request: Request):
    _require_roles(request, "admin", "owner")
    body = await request.json()
    try:
        template = update_template(template_id, **body)
        record_audit_event(
            "template",
            template_id,
            "updated",
            {"fields": sorted(body.keys())},
            actor_user_id=_actor_user_id(request),
        )
        return {"template": template}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/templates/{template_id}")
async def api_delete_template(template_id: str, request: Request):
    _require_roles(request, "admin", "owner")
    delete_template(template_id)
    record_audit_event(
        "template",
        template_id,
        "deleted",
        {},
        actor_user_id=_actor_user_id(request),
    )
    return {"ok": True}


@app.post("/api/templates/{template_id}/render")
async def api_render_template(template_id: str, request: Request):
    _require_roles(request, "agent")
    body = await request.json()
    contact_id = body.get("contact_id", "")
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    rendered = render_template(template, contact)
    return {"rendered": rendered, "template": template, "contact_id": contact_id}


# ====================================================================
#  DASHBOARD API — BROADCAST HISTORY
# ====================================================================

@app.get("/api/broadcasts/history")
@app.get("/api/campaigns/history")
async def api_broadcast_history(request: Request):
    _require_roles(request, "admin", "owner")
    history = get_broadcast_history(limit=50)
    stats = get_broadcast_stats()
    return {"broadcasts": history, "stats": stats, "jobs": list_jobs(kind="broadcast_send", limit=50)}


@app.get("/api/jobs")
async def api_list_jobs(request: Request, kind: str = None, status: str = None, limit: int = 50):
    _require_roles(request, "agent")
    return {"jobs": list_jobs(kind=kind, status=status, limit=limit)}


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str, request: Request):
    _require_roles(request, "agent")
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job": job}


# ====================================================================
#  DASHBOARD API — DAILY DIGEST & AI INSIGHTS
# ====================================================================

@app.get("/api/digest")
async def api_daily_digest(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    return digest


@app.post("/api/digest/generate")
async def api_generate_digest(request: Request):
    _require_roles(request, "admin", "owner")
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    save_digest(digest)
    return digest


@app.get("/api/digest/history")
async def api_digest_history(request: Request):
    _require_roles(request, "agent")
    return {"digests": get_digest_history(limit=10)}


@app.get("/api/insights")
async def api_insights(request: Request):
    _require_roles(request, "agent")
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    return {"insights": digest.get("insights", []), "at_risk": digest.get("at_risk", [])}


@app.get("/api/llm/health")
async def api_llm_health(request: Request):
    _require_roles(request, "admin", "owner")
    return {"providers": llm_health()}


@app.get("/api/analytics/inbox")
async def api_inbox_analytics(request: Request, days: int = 30):
    _require_roles(request, "agent")
    return {"metrics": get_operational_metrics(days=days)}


@app.get("/api/audit")
async def api_audit(request: Request, entity_type: str = None, entity_id: str = None, limit: int = 100):
    _require_roles(request, "admin", "owner")
    return {"events": list_audit_events(entity_type=entity_type, entity_id=entity_id, limit=limit)}


# ====================================================================
#  FRONTEND SERVING
# ====================================================================

@app.get("/")
async def serve_frontend():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "frontend" / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Nazar</h1><p>Frontend not found. Place index.html in frontend/</p>")


# ====================================================================
#  HEALTH CHECK
# ====================================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "nazar",
        "storage_backend": get_storage_backend_name(),
        "whatsapp_configured": _whatsapp_ready(),
        "telegram_configured": telegram_ready(),
        "time": datetime.now(IST).isoformat(),
    }


# ====================================================================
#  MAIN
# ====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    logger.info(f"Starting Nazar on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
