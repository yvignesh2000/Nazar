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
# Fix OpenBLAS thread limit issue in constrained environments
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import asyncio
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import aiohttp
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add core to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from contact_manager import (
    create_contact, get_contact, update_contact, delete_contact,
    list_contacts, get_contact_by_phone, move_stage, update_lead_score,
    add_tag, remove_tag, save_message, get_today_conversation,
    get_conversation_history, import_contacts_csv, get_pipeline_summary,
    contact_exists, PIPELINE_STAGES,
)
from customer_memory import (
    get_relevant_context, add_message as memory_add_message,
    extract_signals_from_message, add_signal, get_customer_summary,
    search as memory_search, delete_customer_vectors,
)
from conversation import handle_inbound, generate_ai_reply, should_handoff
from llm_router import call_llm_safe, get_health_status as llm_health
from handoff_manager import (
    is_bot_active, get_contact_handoff_state, get_all_handoff_states,
    trigger_handoff, resume_bot, mark_human_responded,
    evaluate_handoff, evaluate_response_handoff,
    check_auto_resume, get_handoff_queue, get_handoff_history,
    get_handoff_stats, build_team_notification,
)
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

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# --- Config ---
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "nazar_verify_2026")
WA_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
API_KEY = os.environ.get("NAZAR_API_KEY", "nazar_dev_key")

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

# Bot mode is now managed by handoff_manager (persistent to disk)
# _bot_mode dict removed -- use is_bot_active(contact_id) instead


def _log_task_error(task: asyncio.Task):
    """Callback to log unhandled exceptions from fire-and-forget tasks."""
    if not task.cancelled() and task.exception():
        logger.error(f"Background task failed: {task.exception()}", exc_info=task.exception())


# ====================================================================
#  AUTH MIDDLEWARE
# ====================================================================

def _check_api_key(request: Request):
    """Validate API key for dashboard endpoints."""
    key = request.headers.get("X-Nazar-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ====================================================================
#  CONFIG HELPER
# ====================================================================

def _load_config() -> dict:
    """Load bot configuration from data/config.json."""
    config_path = DATA_DIR / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"business_name": "our company", "bot_enabled": True, "smart_handoff": True}


# ====================================================================
#  WHATSAPP CLOUD API HELPERS
# ====================================================================

async def send_whatsapp_message(phone: str, text: str) -> dict:
    """Send a text message via WhatsApp Cloud API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace("+", ""),
        "type": "text",
        "text": {"body": text},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(WA_API_URL, headers=headers, json=payload) as resp:
            result = await resp.json()
            if resp.status != 200:
                logger.error(f"WhatsApp send failed: {result}")
            return result


async def send_template_message(phone: str, template_name: str, language: str = "en", components: list = None) -> dict:
    """Send a template message via WhatsApp Cloud API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
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
    async with aiohttp.ClientSession() as session:
        async with session.post(WA_API_URL, headers=headers, json=payload) as resp:
            result = await resp.json()
            if resp.status != 200:
                logger.error(f"Template send failed: {result}")
            return result


async def mark_as_read(message_id: str):
    """Mark a WhatsApp message as read."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(WA_API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                err = await resp.text()
                logger.error(f"Mark read failed for {message_id}: {err}")


async def download_whatsapp_media(media_id: str) -> tuple:
    """Download media from WhatsApp Cloud API. Returns (bytes, mime_type)."""
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        meta_url = f"https://graph.facebook.com/v21.0/{media_id}"
        async with session.get(meta_url, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"Media metadata fetch failed: {resp.status}")
            meta = await resp.json()

        download_url = meta.get("url", "")
        mime_type = meta.get("mime_type", "audio/ogg")

        async with session.get(download_url, headers=headers) as resp:
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

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
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
                        t2 = asyncio.create_task(_handle_text_message(phone, text, msg_id))
                        t2.add_done_callback(_log_task_error)

                elif msg_type == "audio":
                    media_id = msg.get("audio", {}).get("id", "")
                    if media_id:
                        t1 = asyncio.create_task(mark_as_read(msg_id))
                        t1.add_done_callback(_log_task_error)
                        t2 = asyncio.create_task(_handle_voice_message(phone, media_id))
                        t2.add_done_callback(_log_task_error)

    return Response(status_code=200)


def _handle_status_update(status: dict):
    """Handle WhatsApp delivery/read status updates."""
    # Update message status in conversation history
    wa_msg_id = status.get("id", "")
    new_status = status.get("status", "")  # sent, delivered, read, failed
    recipient = status.get("recipient_id", "")

    if new_status and recipient:
        logger.info(f"Status update: {wa_msg_id} → {new_status} for {recipient}")
        # TODO: update message status in contact's conversation log


async def _handle_text_message(phone: str, text: str, msg_id: str):
    """Handle an inbound text message with full handoff pipeline."""
    try:
        phone_e164 = f"+{phone}" if not phone.startswith("+") else phone

        # Load config for handoff settings
        config = _load_config()
        handoff_message = config.get(
            "handoff_message",
            "I'll connect you with a team member who can help with this directly.",
        )
        smart_handoff = config.get("smart_handoff", True)
        auto_resume_hours = config.get("auto_resume_hours", 0)
        notify_phone = config.get("notify_phone", "")

        # 1. Get or create contact
        contact = get_contact_by_phone(phone_e164)

        # 2. If bot is off (human mode), just save the message silently
        if contact and not is_bot_active(contact["contact_id"]):
            save_message(contact["contact_id"], "inbound", text, wa_message_id=msg_id)
            logger.info(f"[{phone}] Bot off -- message saved for human")
            return

        contact_id = contact["contact_id"] if contact else None
        contact_name = contact.get("name", "") if contact else ""

        # 3. Get recent messages for AI handoff context
        recent_messages = []
        if contact_id:
            try:
                recent_messages = get_conversation_history(contact_id, days=3)
            except Exception:
                pass

        # 4. Evaluate handoff (keyword + optional AI intent check)
        async def haiku_call(messages):
            return await call_llm_safe(messages, tier="haiku", phone=phone)

        handoff_result = None
        if contact_id:
            handoff_result = await evaluate_handoff(
                contact_id=contact_id,
                message=text,
                recent_messages=recent_messages,
                llm_call=haiku_call if smart_handoff else None,
                contact_name=contact_name,
                contact_phone=phone_e164,
                smart_handoff_enabled=smart_handoff,
            )

        if handoff_result:
            # Save the inbound message first
            if contact_id:
                save_message(contact_id, "inbound", text, wa_message_id=msg_id)

            # Send handoff message to customer
            await send_whatsapp_message(phone, handoff_message)

            # Save the handoff message as outbound
            if contact_id:
                save_message(contact_id, "outbound", handoff_message, sent_by="bot")

            # Notify team if configured
            if notify_phone:
                notification = build_team_notification(
                    contact_name=contact_name,
                    contact_phone=phone_e164,
                    reason=handoff_result.get("reason", "Handoff triggered"),
                    message_excerpt=text,
                )
                t = asyncio.create_task(send_whatsapp_message(notify_phone, notification))
                t.add_done_callback(_log_task_error)

            logger.info(
                f"[{phone}] Handoff triggered: {handoff_result.get('reason', 'unknown')} "
                f"[method={handoff_result.get('detection_method', 'unknown')}]"
            )
            return

        # 5. Normal AI response
        async def llm_call(messages):
            return await call_llm_safe(messages, tier="sonnet", phone=phone)

        response = await handle_inbound(phone_e164, text, llm_call)

        # 6. Check if the AI's own response indicates a handoff
        if contact_id:
            response_handoff = await evaluate_response_handoff(
                contact_id=contact_id,
                ai_response=response,
                contact_name=contact_name,
                contact_phone=phone_e164,
            )
            if response_handoff:
                logger.info(
                    f"[{phone}] AI self-triggered handoff: "
                    f"{response_handoff.get('reason', 'AI response indicated handoff')}"
                )
                # Notify team
                if notify_phone:
                    notification = build_team_notification(
                        contact_name=contact_name,
                        contact_phone=phone_e164,
                        reason=response_handoff.get("reason", "AI initiated handoff"),
                        message_excerpt=response[:150],
                    )
                    t = asyncio.create_task(send_whatsapp_message(notify_phone, notification))
                    t.add_done_callback(_log_task_error)

        await send_whatsapp_message(phone, response)

    except Exception as e:
        logger.error(f"Error handling message from {phone}: {e}", exc_info=True)
        try:
            await send_whatsapp_message(phone, "I'm having a brief issue. A team member will follow up shortly!")
        except Exception:
            pass


async def _handle_voice_message(phone: str, media_id: str):
    """Handle an inbound voice message — transcribe and process."""
    try:
        audio_bytes, mime_type = await download_whatsapp_media(media_id)
        transcript = await transcribe_audio(audio_bytes, mime_type)
        logger.info(f"[{phone}] Voice transcribed: {transcript[:60]}...")
        await _handle_text_message(phone, transcript, "")
    except TranscriptionError as e:
        logger.error(f"Transcription failed for {phone}: {e}")
        await send_whatsapp_message(phone, "I couldn't process that voice note. Could you type it out instead?")
    except Exception as e:
        logger.error(f"Voice handling failed for {phone}: {e}", exc_info=True)


# ====================================================================
#  DASHBOARD API — OVERVIEW
# ====================================================================

@app.get("/api/overview")
async def api_overview(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    now = datetime.now(IST)

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
            "bot_conversations_today": 0,  # TODO: track
        },
        "pipeline": pipeline,
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
    _check_api_key(request)
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
    _check_api_key(request)
    contacts = list_contacts(stage=stage, tag=tag, assigned_to=assigned_to)
    return {"contacts": contacts, "total": len(contacts)}


@app.post("/api/contacts")
async def api_create_contact(request: Request):
    _check_api_key(request)
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
        return {"contact": contact}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/contacts/{contact_id}")
async def api_get_contact(contact_id: str, request: Request):
    _check_api_key(request)
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    return {"contact": contact}


@app.patch("/api/contacts/{contact_id}")
async def api_update_contact(contact_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    try:
        contact = update_contact(contact_id, **body)
        return {"contact": contact}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/contacts/{contact_id}")
async def api_delete_contact(contact_id: str, request: Request):
    _check_api_key(request)
    try:
        delete_contact(contact_id)
        delete_customer_vectors(contact_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/contacts/import")
async def api_import_contacts(request: Request):
    _check_api_key(request)
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
async def api_list_conversations(request: Request, status: str = None):
    _check_api_key(request)
    contacts = list_contacts()

    conversations = []
    for c in contacts:
        today_msgs = get_today_conversation(c["contact_id"])
        last_msg = today_msgs[-1] if today_msgs else None
        conversations.append({
            "contact_id": c["contact_id"],
            "name": c.get("name", "Unknown"),
            "phone": c.get("phone", ""),
            "stage": c.get("pipeline_stage", "New"),
            "tags": c.get("tags", []),
            "lead_score": c.get("lead_score", 0),
            "last_message": last_msg.get("content", "")[:100] if last_msg else "",
            "last_time": last_msg.get("timestamp", "") if last_msg else c.get("last_replied_at", ""),
            "bot_mode": is_bot_active(c["contact_id"]),
            "message_count": c.get("total_messages", 0),
        })
    conversations.sort(key=lambda x: x["last_time"] or "", reverse=True)
    return {"conversations": conversations}


@app.get("/api/conversations/{contact_id}")
async def api_get_conversation(contact_id: str, request: Request, days: int = 7):
    _check_api_key(request)
    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    messages = get_conversation_history(contact_id, days=days)
    memory_summary = get_customer_summary(contact_id)
    return {
        "contact": contact,
        "messages": messages,
        "memory": memory_summary,
        "bot_mode": is_bot_active(contact_id),
        "handoff_state": get_contact_handoff_state(contact_id),
    }


@app.post("/api/conversations/{contact_id}/send")
async def api_send_message(contact_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    text = body.get("message", "")
    if not text:
        raise HTTPException(400, "message is required")

    contact = get_contact(contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")

    phone = contact["phone"]

    # Send via WhatsApp
    result = await send_whatsapp_message(phone, text)

    # Save to conversation history
    wa_msg_id = ""
    if "messages" in result:
        wa_msg_id = result["messages"][0].get("id", "")

    save_message(contact_id, "outbound", text, sent_by="human", wa_message_id=wa_msg_id)
    memory_add_message(contact_id, "outbound", text)

    # Mark that a human has responded to this handoff
    if not is_bot_active(contact_id):
        mark_human_responded(contact_id)

    # Update contact
    update_contact(contact_id, last_contacted_at=datetime.now(IST).isoformat())

    return {"ok": True, "wa_message_id": wa_msg_id}


@app.post("/api/conversations/{contact_id}/handover")
async def api_handover(contact_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    bot_on = body.get("bot_mode", True)

    if bot_on:
        entry = resume_bot(contact_id, resumed_by="manual", reason="Toggled from dashboard")
    else:
        contact = get_contact(contact_id)
        entry = trigger_handoff(
            contact_id=contact_id,
            reason="Manually switched to human mode from dashboard",
            triggered_by="manual",
            contact_name=contact.get("name", "") if contact else "",
            contact_phone=contact.get("phone", "") if contact else "",
            detection_method="manual",
        )

    logger.info(f"Bot mode for {contact_id}: {'ON' if bot_on else 'OFF'}")
    return {"bot_mode": bot_on, "handoff_state": entry}


# ====================================================================
#  DASHBOARD API — HANDOFF QUEUE
# ====================================================================

@app.get("/api/handoffs")
async def api_handoff_queue(request: Request):
    _check_api_key(request)
    queue = get_handoff_queue()
    stats = get_handoff_stats()
    return {"queue": queue, "stats": stats}


@app.get("/api/handoffs/history")
async def api_handoff_history(request: Request):
    _check_api_key(request)
    history = get_handoff_history(limit=100)
    return {"history": history}


@app.get("/api/handoffs/stats")
async def api_handoff_stats(request: Request):
    _check_api_key(request)
    return get_handoff_stats()


@app.post("/api/handoffs/{contact_id}/resume")
async def api_resume_bot(contact_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    reason = body.get("reason", "Resumed from dashboard")
    entry = resume_bot(contact_id, resumed_by="manual", reason=reason)
    return {"ok": True, "handoff_state": entry}


# ====================================================================
#  DASHBOARD API — MEMORY
# ====================================================================

@app.get("/api/contacts/{contact_id}/memory")
async def api_contact_memory(contact_id: str, request: Request, query: str = ""):
    _check_api_key(request)
    summary = get_customer_summary(contact_id)
    results = []
    if query:
        results = memory_search(contact_id, query, n_results=20)
    return {"summary": summary, "search_results": results}


# ====================================================================
#  DASHBOARD API — PIPELINE
# ====================================================================

@app.get("/api/pipeline")
async def api_pipeline(request: Request):
    _check_api_key(request)
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
    _check_api_key(request)
    body = await request.json()
    new_stage = body.get("stage", "")
    try:
        contact = move_stage(contact_id, new_stage)
        return {"contact": contact}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ====================================================================
#  DASHBOARD API — FOLLOW-UPS
# ====================================================================

@app.get("/api/followups")
async def api_followups(request: Request):
    _check_api_key(request)
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
async def api_broadcast(request: Request):
    _check_api_key(request)
    body = await request.json()
    message = body.get("message", "")
    template_name = body.get("template", "")
    filter_stage = body.get("stage")
    filter_tag = body.get("tag")
    contact_ids = body.get("contact_ids", [])

    if not message and not template_name:
        raise HTTPException(400, "message or template required")

    # Get target contacts
    if contact_ids:
        targets = [get_contact(cid) for cid in contact_ids]
        targets = [c for c in targets if c]
    else:
        targets = list_contacts(stage=filter_stage, tag=filter_tag)

    results = {"sent": 0, "failed": 0, "details": []}

    for contact in targets:
        phone = contact["phone"]
        try:
            if template_name:
                await send_template_message(phone, template_name)
            else:
                await send_whatsapp_message(phone, message)

            save_message(contact["contact_id"], "outbound", message or f"[template: {template_name}]", sent_by="broadcast")
            results["sent"] += 1
            results["details"].append({"phone": phone, "status": "sent"})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"phone": phone, "status": "failed", "error": str(e)})

        # Rate limiting — don't spam WhatsApp API
        await asyncio.sleep(0.1)

    return results


# ====================================================================
#  DASHBOARD API — CONFIG
# ====================================================================

@app.get("/api/config")
async def api_get_config(request: Request):
    _check_api_key(request)
    config_path = DATA_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {
        "business_name": "",
        "bot_enabled": True,
        "bot_persona": "professional",
        "welcome_message": "Hi! How can I help you today?",
        "handoff_message": "I'll connect you with a team member who can help.",
        "whatsapp_connected": bool(WHATSAPP_ACCESS_TOKEN),
    }


@app.put("/api/config")
async def api_update_config(request: Request):
    _check_api_key(request)
    body = await request.json()
    config_path = DATA_DIR / "config.json"

    existing = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text())

    existing.update(body)
    config_path.write_text(json.dumps(existing, indent=2))
    return existing


# ====================================================================
#  DASHBOARD API — KNOWLEDGE BASE
# ====================================================================

@app.post("/api/kb/upload")
async def api_upload_kb(request: Request):
    _check_api_key(request)
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
    _check_api_key(request)
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
    _check_api_key(request)
    config_path = DATA_DIR / "config.json"
    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text())

    team = config.get("team", [
        {"id": "owner", "name": "Admin", "role": "Owner", "status": "active"},
    ])
    return {"team": team}




# ====================================================================
#  DASHBOARD API — TEMPLATES
# ====================================================================

@app.get("/api/templates")
async def api_list_templates(request: Request, category: str = None, status: str = None):
    _check_api_key(request)
    templates = list_templates(category=category, status=status)
    stats = get_template_stats()
    return {"templates": templates, "stats": stats}


@app.get("/api/templates/{template_id}")
async def api_get_template(template_id: str, request: Request):
    _check_api_key(request)
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return {"template": template}


@app.post("/api/templates")
async def api_create_template(request: Request):
    _check_api_key(request)
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
        return {"template": template}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/templates/{template_id}")
async def api_update_template(template_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    try:
        template = update_template(template_id, **body)
        return {"template": template}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/templates/{template_id}")
async def api_delete_template(template_id: str, request: Request):
    _check_api_key(request)
    delete_template(template_id)
    return {"ok": True}


@app.post("/api/templates/{template_id}/render")
async def api_render_template(template_id: str, request: Request):
    _check_api_key(request)
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
async def api_broadcast_history(request: Request):
    _check_api_key(request)
    history = get_broadcast_history(limit=50)
    stats = get_broadcast_stats()
    return {"broadcasts": history, "stats": stats}


# ====================================================================
#  DASHBOARD API — DAILY DIGEST & AI INSIGHTS
# ====================================================================

@app.get("/api/digest")
async def api_daily_digest(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    return digest


@app.post("/api/digest/generate")
async def api_generate_digest(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    save_digest(digest)
    return digest


@app.get("/api/digest/history")
async def api_digest_history(request: Request):
    _check_api_key(request)
    return {"digests": get_digest_history(limit=10)}


@app.get("/api/insights")
async def api_insights(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    pipeline = get_pipeline_summary()
    digest = generate_daily_digest(contacts, pipeline)
    return {"insights": digest.get("insights", []), "at_risk": digest.get("at_risk", [])}


@app.get("/api/llm/health")
async def api_llm_health(request: Request):
    _check_api_key(request)
    return {"providers": llm_health()}


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
#  AUTO-RESUME BACKGROUND TASK
# ====================================================================

async def _auto_resume_loop():
    """Background loop that checks for timed-out handoffs every 5 minutes."""
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            config = _load_config()
            auto_resume_hours = config.get("auto_resume_hours", 0)
            if auto_resume_hours > 0:
                resumed = check_auto_resume(auto_resume_hours)
                if resumed:
                    logger.info(f"Auto-resumed {len(resumed)} contact(s): {resumed}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auto-resume loop error: {e}")


@app.on_event("startup")
async def startup_event():
    """Start background tasks."""
    asyncio.create_task(_auto_resume_loop())
    logger.info("Handoff auto-resume background task started")


# ====================================================================
#  HEALTH CHECK
# ====================================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "nazar",
        "whatsapp_configured": bool(WHATSAPP_ACCESS_TOKEN),
        "time": datetime.now(IST).isoformat(),
    }


# ====================================================================
#  MAIN
# ====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    logger.info(f"Starting Nazar on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
