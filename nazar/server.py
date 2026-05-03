# -*- coding: utf-8 -*-
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

# Fix SQLite version for ChromaDB on older systems (needs >= 3.35.0)
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import asyncio
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

import aiohttp
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
from llm_router import call_llm, call_llm_safe, get_health_status as llm_health
from handoff_manager import (
    is_bot_active, get_contact_handoff_state, get_all_handoff_states,
    trigger_handoff, resume_bot, mark_human_responded,
    evaluate_handoff, evaluate_response_handoff,
    check_auto_resume, get_handoff_queue, get_handoff_history,
    get_handoff_stats, build_team_notification,
)
from transcription import transcribe_audio, TranscriptionError
from outbound import (
    execute_campaign_send, personalize_message, generate_followup_context,
    create_campaign, get_campaign, update_campaign,
    get_campaign_history, get_campaign_stats,
)
from reply_mode import (
    get_contact_reply_mode, set_contact_reply_mode, clear_contact_reply_mode,
    get_effective_reply_mode, save_campaign_kb, get_campaign_kb, delete_campaign_kb,
    associate_contacts_to_campaign, get_contact_campaign,
    save_draft, get_draft, get_all_pending_drafts,
    approve_draft, reject_draft, clear_draft,
    VALID_MODES,
)
from template_manager import (
    list_templates, get_template, get_template_by_name, create_template,
    update_template, delete_template, increment_usage as increment_template_usage, render_template,
    suggest_template, get_template_stats, TEMPLATE_CATEGORIES,
)
from digest_engine import (
    get_followup_queue, generate_daily_digest, format_digest_for_whatsapp,
    save_digest, get_digest_history,
)
from analytics import (
    log_event, get_analytics_snapshot, get_conversation_stats,
    get_pipeline_analytics, get_campaign_analytics, get_ai_performance,
    get_lead_quality_report, get_trend,
)
from auth_manager import (
    validate_api_key, validate_token, check_permission,
    create_workspace, get_workspace, list_workspaces,
    create_user, get_user, list_workspace_users, update_user, delete_user,
    change_password, reset_password,
    login, bootstrap_default_workspace,
    create_invite, accept_invite, get_workspace_invites,
    regenerate_api_key, ROLES,
)
from billing import (
    create_subscription, get_subscription, update_subscription,
    upgrade_plan, cancel_subscription, is_subscription_active,
    get_plan_limits, get_usage_summary, get_plans_for_display,
    check_limit, increment_usage, set_usage,
    handle_stripe_webhook, PLANS,
)
from onboarding import (
    get_onboarding_state, mark_step_done, skip_step,
    reset_onboarding, auto_detect_progress, get_readiness_checklist,
)
from websocket_manager import ws_manager
from optout_manager import (
    is_stop_message, is_start_message, record_optout, record_optin,
    is_opted_out, can_message, OPT_OUT_REPLY, OPT_IN_REPLY,
)
from job_queue import job_queue, JobStatus
from rate_limiter import wa_rate_limiter, DailyLimitExceeded
from workspace_context import set_workspace, get_workspace, set_channel, get_channel, clear_context
from channel import (
    create_channel as create_channel_record,
    get_channel as get_channel_record,
    get_channel_by_phone_number_id,
    list_channels, update_channel as update_channel_record,
    delete_channel as delete_channel_record,
    get_primary_channel, get_channel_config, get_channel_credentials,
    ensure_default_channel, channel_count,
)
from assignment_manager import (
    assign_conversation, manual_assign, claim_conversation,
    transfer_conversation, resolve_conversation,
    get_assignment, get_agent_conversations,
    get_unassigned_queue, get_agent_workload, get_all_assignments,
)
from audit import log_audit, get_audit_log, get_audit_stats
from segmentation import (
    evaluate_segment, preview_segment,
    save_segment, list_segments, get_segment, delete_segment,
    SEGMENTABLE_FIELDS, OPERATORS,
)
import knowledge_base as kb_manager
import webhook_dispatcher as webhook_dispatcher_mod
from auth_manager import revoke_token
from contact_groups import (
    create_group, list_groups, get_group, update_group, delete_group,
    add_members, remove_members, get_group_members, get_contact_groups,
    get_contacts_by_group_ids, GROUP_COLORS,
)
from pipeline_classifier import classify_contact_stage, should_classify
from service_window import compute_window as sw_compute_window, batch_window_status, classify_campaign_targets
from meta_template_sync import (
    submit_template_to_meta, get_meta_template_status,
    delete_template_from_meta, sync_all_templates,
    handle_template_status_webhook, is_meta_configured,
)
from schemas import (
    CreateContactRequest, UpdateContactRequest, ImportContactsRequest,
    MovePipelineRequest, SendMessageRequest, HandoverRequest,
    SetReplyModeRequest, ApproveDraftRequest,
    CreateTemplateRequest, UpdateTemplateRequest, RenderTemplateRequest,
    CreateCampaignRequest, RetargetCampaignRequest,
    UpdateConfigRequest, UploadKBRequest,
    LoginRequest, CreateUserRequest, UpdateUserRequest, ChangePasswordRequest,
    UpgradePlanRequest, CancelSubscriptionRequest,
    CreateInviteRequest, AcceptInviteRequest,
    SaveApiKeysRequest, SimulateMessageRequest, ResumeHandoffRequest,
    CreateChannelRequest, UpdateChannelRequest,
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

app = FastAPI(title="Nazar", version="1.0.0", docs_url=None, redoc_url=None)

# --- CORS configuration ---
# Production: set NAZAR_CORS_ORIGINS to a comma-separated allowlist
#   e.g. NAZAR_CORS_ORIGINS="https://app.nazar.example,https://admin.nazar.example"
# Dev: defaults to common localhost origins for the React dashboard.
# Wildcard ("*") is still supported for explicit opt-in but logs a warning
# and is incompatible with credentialed requests (browsers reject that combo).
_cors_env = os.environ.get("NAZAR_CORS_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ]

_cors_allow_credentials = True
if "*" in _cors_origins:
    logger.warning(
        "CORS: wildcard origin '*' is configured. Disabling credentialed CORS "
        "(browsers reject '*' with credentials). Set NAZAR_CORS_ORIGINS to an "
        "explicit allowlist for production."
    )
    _cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Requested-With",
        "X-CSRF-Token",
    ],
    max_age=600,
)

# --- Security middleware: headers + basic rate limiting ---
import time
from collections import defaultdict

_rate_limit_store: dict = defaultdict(list)   # ip -> [timestamps]
RATE_LIMIT_WINDOW = 60       # seconds
RATE_LIMIT_MAX = 120         # max requests per window per IP

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Add security headers, CSRF protection, and rate limiting."""
    # CSRF protection: reject state-changing requests from foreign origins
    # This prevents cross-site attacks where a malicious page submits forms to our API
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        # Allow requests with no origin (server-to-server, CLI tools, mobile apps)
        # and requests with API key auth (not browser sessions)
        has_api_key = bool(request.headers.get("X-Nazar-Key", ""))
        if origin and not has_api_key:
            # For browser-originated requests, validate the origin
            host = request.headers.get("host", "")
            allowed_origins = {f"http://{host}", f"https://{host}", "http://localhost:5173"}
            if origin not in allowed_origins:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: origin mismatch"},
                )

    # Rate limiting (skip for static assets and health checks)
    if not request.url.path.startswith("/assets") and request.url.path != "/health":
        # Use IP + API key fingerprint as rate limit key to prevent bypass
        client_ip = request.client.host if request.client else "unknown"
        api_key_finger = ""
        auth_header = request.headers.get("Authorization", "")
        nazar_key = request.headers.get("X-Nazar-Key", "")
        if auth_header:
            api_key_finger = auth_header[-8:]  # last 8 chars as fingerprint
        elif nazar_key:
            api_key_finger = nazar_key[-8:]
        rate_key = f"{client_ip}:{api_key_finger}" if api_key_finger else client_ip

        now = time.time()
        timestamps = _rate_limit_store[rate_key]
        # Prune old entries
        _rate_limit_store[rate_key] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
        if len(_rate_limit_store[rate_key]) >= RATE_LIMIT_MAX:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
        _rate_limit_store[rate_key].append(now)
        # Prune stale rate limit keys every 1000 requests
        if len(_rate_limit_store) > 5000:
            stale_keys = [k for k, v in _rate_limit_store.items() if not v or now - v[-1] > RATE_LIMIT_WINDOW * 2]
            for k in stale_keys:
                del _rate_limit_store[k]

    response = await call_next(request)

    # Clear thread-local context after each request
    clear_context()

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; connect-src 'self' wss: ws:;"
    )
    return response

# Track processed messages to avoid duplicates (persisted to SQLite)
_processed_messages: deque = deque(maxlen=10000)


def _load_recent_message_ids():
    """Load recent wa_message_ids from DB to prevent duplicate processing after restart."""
    try:
        from database import get_db as _dedup_get_db
        with _dedup_get_db() as conn:
            rows = conn.execute(
                "SELECT wa_message_id FROM messages "
                "WHERE wa_message_id IS NOT NULL AND wa_message_id != '' "
                "ORDER BY timestamp DESC LIMIT 10000"
            ).fetchall()
        for row in rows:
            mid = row["wa_message_id"]
            if mid and mid not in _processed_messages:
                _processed_messages.append(mid)
        logger.info("Loaded %d recent message IDs for dedup", len(_processed_messages))
    except Exception as e:
        logger.warning("Could not load message IDs for dedup: %s", e)

# Bot mode is now managed by handoff_manager (persistent to disk)
# _bot_mode dict removed -- use is_bot_active(contact_id) instead


def _log_task_error(task: asyncio.Task):
    """Callback to log unhandled exceptions from fire-and-forget tasks."""
    if not task.cancelled() and task.exception():
        logger.error(f"Background task failed: {task.exception()}", exc_info=task.exception())


# ====================================================================
#  AUTH MIDDLEWARE
# ====================================================================

def _check_api_key(request: Request) -> dict:
    """
    Validate API key or session token for dashboard endpoints.

    Accepts:
      - X-Nazar-Key: <api_key>      (legacy + workspace API keys)
      - Authorization: Bearer <jwt>  (session tokens from login)

    Returns the auth context dict (with workspace info).
    Sets the thread-local workspace context for multi-tenancy.
    Raises 401 if invalid.
    """
    # 1. Try session token (Authorization: Bearer ...)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        ctx = validate_token(token)
        if ctx:
            set_workspace(ctx.get("workspace_id", "default"))
            return ctx

    # 2. Try API key (X-Nazar-Key header)
    key = request.headers.get("X-Nazar-Key", "")
    if key:
        workspace = validate_api_key(key)
        if workspace:
            ws_id = workspace["workspace_id"]
            set_workspace(ws_id)
            return {"workspace_id": ws_id, "workspace": workspace, "user": None}

    raise HTTPException(status_code=401, detail="Invalid API key or session token")


def _check_subscription_active(ctx: dict) -> None:
    """
    Verify the workspace has an active or trialing subscription.
    Raises HTTP 402 if the subscription is expired/canceled.
    Called on state-changing endpoints (send message, create campaign, etc.)
    """
    workspace_id = ctx.get("workspace_id", "default")
    if not is_subscription_active(workspace_id):
        raise HTTPException(
            status_code=402,
            detail="Your subscription has expired or been canceled. "
                   "Please upgrade your plan to continue using Nazar.",
        )


def _check_billing_limit(ctx: dict, metric: str, amount: int = 1) -> None:
    """
    Check if a workspace is within its plan limits for a metric.
    Raises HTTP 403 if over the limit.
    """
    workspace_id = ctx.get("workspace_id", "default")
    result = check_limit(workspace_id, metric, amount)
    if not result["allowed"]:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Plan limit reached for {metric}. "
                f"Current usage: {result['current']}/{result['limit']}. "
                f"Please upgrade your plan."
            ),
        )


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


def _save_config(config: dict):
    """Save bot configuration to data/config.json."""
    config_path = DATA_DIR / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ====================================================================
#  WHATSAPP CLOUD API HELPERS
# ====================================================================

def _build_template_components(template: dict, contact: dict) -> list:
    """
    Build WhatsApp API template component parameters from a template definition
    and per-contact field values.

    Returns a list of component dicts compatible with the WhatsApp Cloud API.

    The variable resolution order mirrors ``render_template()`` so the Meta API
    receives the same values the user sees in preview.
    """
    components = []

    # Shared variable → value map (same logic as template_manager.render_template)
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

    # Body parameters
    variables = template.get("variables", [])
    if variables:
        params = []
        for var in variables:
            value = var_map.get(var) or contact.get(var) or contact.get(f"custom_{var}") or str(var)
            # WhatsApp rejects empty parameter text — always send at least a space
            if not value or not str(value).strip():
                value = str(var)
            params.append({"type": "text", "text": str(value)})
        if params:
            components.append({"type": "body", "parameters": params})

    # Header (image/document)
    header = template.get("header") or {}
    if isinstance(header, dict):
        header_type = header.get("type", "")
        if header_type == "image" and header.get("url"):
            components.append({
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": header["url"]}}],
            })
        elif header_type == "document" and header.get("url"):
            components.append({
                "type": "header",
                "parameters": [{"type": "document", "document": {"link": header["url"]}}],
            })

    return components

async def send_whatsapp_message(phone: str, text: str) -> dict:
    """Send a text message via WhatsApp Cloud API."""
    # Normalise to E.164 for opt-out check
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    if not can_message(phone_e164):
        logger.info(f"[{phone}] Skipping send — contact is opted out")
        return {"skipped": True, "reason": "opted_out"}

    # Apply rate limiting
    try:
        await wa_rate_limiter.acquire()
    except DailyLimitExceeded as e:
        logger.error(f"WhatsApp daily limit exceeded: {e}")
        raise

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
    try:
        await wa_rate_limiter.acquire()
    except DailyLimitExceeded as e:
        logger.error(f"WhatsApp daily limit exceeded on template send: {e}")
        raise

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


async def send_interactive_buttons(phone: str, body_text: str, buttons: list, header: str = "", footer: str = "") -> dict:
    """
    Send a WhatsApp interactive button message (up to 3 buttons).

    Args:
        phone: recipient phone number
        body_text: main message body
        buttons: list of {"id": "btn_1", "title": "Click Me"} dicts (max 3)
        header: optional header text
        footer: optional footer text

    WhatsApp docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages
    """
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    if not can_message(phone_e164):
        return {"skipped": True, "reason": "opted_out"}

    await wa_rate_limiter.acquire()

    action_buttons = []
    for b in buttons[:3]:
        action_buttons.append({
            "type": "reply",
            "reply": {"id": b["id"], "title": b["title"][:20]},
        })

    interactive = {
        "type": "button",
        "body": {"text": body_text[:1024]},
        "action": {"buttons": action_buttons},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace("+", ""),
        "type": "interactive",
        "interactive": interactive,
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(WA_API_URL, headers=headers, json=payload) as resp:
            result = await resp.json()
            if resp.status != 200:
                logger.error(f"Interactive buttons send failed: {result}")
            return result


async def send_interactive_list(phone: str, body_text: str, button_text: str, sections: list, header: str = "", footer: str = "") -> dict:
    """
    Send a WhatsApp interactive list message.

    Args:
        phone: recipient phone number
        body_text: main message body
        button_text: text on the list button (e.g., "View Options")
        sections: list of {"title": "Section Name", "rows": [{"id": "row_1", "title": "Row Title", "description": "optional"}]}
        header: optional header text
        footer: optional footer text

    WhatsApp docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages
    """
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    if not can_message(phone_e164):
        return {"skipped": True, "reason": "opted_out"}

    await wa_rate_limiter.acquire()

    interactive = {
        "type": "list",
        "body": {"text": body_text[:1024]},
        "action": {
            "button": button_text[:20],
            "sections": sections[:10],
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": phone.replace("+", ""),
        "type": "interactive",
        "interactive": interactive,
    }
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(WA_API_URL, headers=headers, json=payload) as resp:
            result = await resp.json()
            if resp.status != 200:
                logger.error(f"Interactive list send failed: {result}")
            return result


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
    # ── Signature verification (HMAC-SHA256) ──────────────────────────
    # Meta signs every payload with your App Secret.
    # Without this check, anyone who knows your URL can inject messages.
    import hmac as _hmac
    import hashlib as _hashlib

    wa_app_secret = os.environ.get("WA_APP_SECRET", "")
    raw_body = await request.body()

    if not wa_app_secret:
        # No secret — reject ALL inbound webhooks for security.
        # Set WA_APP_SECRET in your .env to enable webhook processing.
        logger.error(
            "WA_APP_SECRET is not configured — rejecting webhook request. "
            "Set WA_APP_SECRET in .env to enable webhook processing."
        )
        raise HTTPException(
            status_code=503,
            detail="Webhook signature verification not configured. Set WA_APP_SECRET.",
        )

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + _hmac.new(
        wa_app_secret.encode(), raw_body, _hashlib.sha256
    ).hexdigest()
    if not _hmac.compare_digest(expected, signature_header):
        logger.warning("Webhook signature mismatch — request rejected")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except Exception:
        return Response(status_code=200)
    # ─────────────────────────────────────────────────────────────────

    entries = body.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            field = change.get("field", "")
            messages = value.get("messages", [])
            statuses = value.get("statuses", [])

            # ── Channel routing ──────────────────────────────────────
            # Extract phone_number_id from Meta payload metadata to
            # determine which channel this message belongs to.
            metadata = value.get("metadata", {})
            incoming_phone_number_id = metadata.get("phone_number_id", "")
            if incoming_phone_number_id:
                channel_record = get_channel_by_phone_number_id(incoming_phone_number_id)
                if channel_record:
                    set_workspace(channel_record["workspace_id"])
                    set_channel(channel_record["id"])
                else:
                    # Fall back to default channel (backward compat with env vars)
                    if incoming_phone_number_id == WHATSAPP_PHONE_NUMBER_ID:
                        set_channel("default")
                    else:
                        logger.warning(
                            "Webhook received for unknown phone_number_id=%s — skipping",
                            incoming_phone_number_id,
                        )
                        continue
            # ─────────────────────────────────────────────────────────

            # Handle template status update webhooks
            # Meta sends these with field="message_template_status_update"
            if field == "message_template_status_update":
                try:
                    result = handle_template_status_webhook(value)
                    if result.get("handled"):
                        logger.info(
                            "Template status webhook: %s → %s",
                            result.get("template_name"), result.get("new_status"),
                        )
                        # Notify dashboard via WebSocket
                        t_ws = asyncio.create_task(ws_manager.broadcast({
                            "type": "template_status_update",
                            "template_name": result.get("template_name", ""),
                            "old_status": result.get("old_status", ""),
                            "new_status": result.get("new_status", ""),
                            "event": result.get("event", ""),
                        }))
                        t_ws.add_done_callback(_log_task_error)
                except Exception as e:
                    logger.error("Template status webhook error: %s", e)
                continue

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

                # CTWA (Click-to-WhatsApp) Ad Attribution
                # When a user clicks a WhatsApp ad on Facebook/Instagram,
                # Meta includes a "referral" object in the first message.
                referral = msg.get("referral") or msg.get("context", {}).get("referred_product") or None
                if referral:
                    _handle_ctwa_referral(phone, referral, msg_id)

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

                elif msg_type in ("image", "video", "document", "sticker"):
                    media_obj = msg.get(msg_type, {})
                    media_id = media_obj.get("id", "")
                    caption = media_obj.get("caption", "")
                    if media_id:
                        t1 = asyncio.create_task(mark_as_read(msg_id))
                        t1.add_done_callback(_log_task_error)
                        t2 = asyncio.create_task(
                            _handle_media_message(phone, media_id, msg_type, msg_id, caption)
                        )
                        t2.add_done_callback(_log_task_error)

    return Response(status_code=200)


def _handle_ctwa_referral(phone: str, referral: dict, msg_id: str):
    """
    Track Click-to-WhatsApp (CTWA) ad attribution.

    When a user clicks a WhatsApp ad on Facebook/Instagram, Meta includes:
      - source_url: the ad URL
      - source_id: the ad ID
      - source_type: "ad" for paid, "post" for organic
      - headline: the ad headline
      - body: the ad body text
      - media_type: "image" or "video"
      - ctwa_clid: click ID for conversion tracking

    This data is stored as the contact's source + tags for analytics.
    """
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    source_type = referral.get("source_type", "unknown")
    source_url = referral.get("source_url", "")
    source_id = referral.get("source_id", "")
    headline = referral.get("headline", "")
    ctwa_clid = referral.get("ctwa_clid", "")

    logger.info(
        "[%s] CTWA referral: type=%s, source_id=%s, headline=%s, clid=%s",
        phone, source_type, source_id, headline, ctwa_clid,
    )

    try:
        contact = get_contact_by_phone(phone_e164)
        if contact:
            # Update existing contact with ad attribution
            update_fields = {}
            if source_type == "ad":
                update_fields["source"] = f"ctwa_ad:{source_id}" if source_id else "ctwa_ad"
            else:
                update_fields["source"] = f"ctwa_{source_type}"

            update_contact(contact["contact_id"], **update_fields)

            # Add CTWA tags
            ctwa_tag = f"ctwa:{source_type}"
            add_tag(contact["contact_id"], ctwa_tag)
            if source_id:
                add_tag(contact["contact_id"], f"ad:{source_id}")
        else:
            # Will be auto-created by _handle_text_message with source info
            # Store in a temporary cache for the contact creation
            _ctwa_pending[phone_e164] = {
                "source": f"ctwa_ad:{source_id}" if source_id else f"ctwa_{source_type}",
                "source_id": source_id,
                "source_url": source_url,
                "headline": headline,
                "ctwa_clid": ctwa_clid,
                "timestamp": datetime.now(IST).isoformat(),
            }

        # Log the ad attribution event for analytics
        log_event("ctwa_referral", contact_id=contact["contact_id"] if contact else "",
                  metadata={
                      "source_type": source_type,
                      "source_id": source_id,
                      "headline": headline,
                      "ctwa_clid": ctwa_clid,
                  })

    except Exception as e:
        logger.error(f"[{phone}] CTWA referral tracking failed: {e}", exc_info=True)


# Temporary storage for CTWA attribution pending contact creation
_ctwa_pending: dict = {}


def _handle_status_update(status: dict):
    """
    Handle WhatsApp delivery/read status updates.

    Updates:
    1. Message status in the messages table (sent → delivered → read → failed)
    2. Campaign delivered/read/replied counters via campaign_contacts linkage

    Prevents double-counting by checking the existing status before incrementing:
    statuses follow a strict progression: sent → delivered → read.
    A 'delivered' update is only counted if the current status is 'sent'.
    """
    wa_msg_id = status.get("id", "")
    new_status = status.get("status", "")  # sent, delivered, read, failed
    recipient = status.get("recipient_id", "")

    if not new_status or not recipient:
        return

    logger.info(f"Status update: {wa_msg_id} → {new_status} for {recipient}")

    try:
        from database import get_db

        with get_db() as conn:
            # 1. Update message status in messages table (only advance, never regress)
            old_status = None
            if wa_msg_id:
                msg_row = conn.execute(
                    "SELECT status FROM messages WHERE wa_message_id = ?",
                    (wa_msg_id,),
                ).fetchone()
                old_status = msg_row["status"] if msg_row else None

                # Status progression: sent → delivered → read | failed
                STATUS_ORDER = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}
                old_rank = STATUS_ORDER.get(old_status, -1)
                new_rank = STATUS_ORDER.get(new_status, -1)

                if new_rank > old_rank or new_status == "failed":
                    conn.execute(
                        "UPDATE messages SET status = ? WHERE wa_message_id = ?",
                        (new_status, wa_msg_id),
                    )
                else:
                    # Status already at or past this level — skip to prevent double-count
                    return

            # 2. Update campaign counters via campaign_contacts linkage
            # Find the contact for this recipient phone
            phone_e164 = f"+{recipient}" if not recipient.startswith("+") else recipient
            phone_raw = recipient.replace("+", "")
            row = conn.execute(
                "SELECT id FROM contacts WHERE phone = ? OR phone = ?",
                (phone_e164, phone_raw),
            ).fetchone()
            if not row:
                return

            contact_id = row["id"]

            # Look up active campaign association
            cc_row = conn.execute(
                "SELECT campaign_id FROM campaign_contacts WHERE contact_id = ?",
                (contact_id,),
            ).fetchone()
            if not cc_row:
                return

            campaign_id = cc_row["campaign_id"]

            # Increment the appropriate campaign counter
            if new_status == "delivered":
                conn.execute(
                    "UPDATE campaigns SET delivered = delivered + 1 WHERE id = ?",
                    (campaign_id,),
                )
            elif new_status == "read":
                conn.execute(
                    "UPDATE campaigns SET read_count = read_count + 1 WHERE id = ?",
                    (campaign_id,),
                )
            elif new_status == "failed":
                # Check for specific error codes
                errors = status.get("errors", [])
                error_code = errors[0].get("code", 0) if errors else 0
                if error_code == 470:
                    # 470 = contact not on WhatsApp
                    conn.execute(
                        "UPDATE campaigns SET not_on_whatsapp = not_on_whatsapp + 1, "
                        "failed = failed + 1 WHERE id = ?",
                        (campaign_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE campaigns SET failed = failed + 1 WHERE id = ?",
                        (campaign_id,),
                    )

            logger.debug(
                "Campaign %s counter updated: %s for contact %s",
                campaign_id, new_status, contact_id,
            )

    except Exception as e:
        logger.error(f"Status update processing error: {e}", exc_info=True)


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

        # 0. Check opt-out / STOP before doing anything
        if is_stop_message(text):
            record_optout(phone_e164, reason="STOP message", message=text)
            await send_whatsapp_message(phone, OPT_OUT_REPLY)
            logger.info(f"[{phone}] STOP received — opted out")
            return

        if is_start_message(text) and is_opted_out(phone_e164):
            record_optin(phone_e164)
            await send_whatsapp_message(phone, OPT_IN_REPLY)
            logger.info(f"[{phone}] START received — opted back in")
            return

        # Block all messages to opted-out contacts
        if not can_message(phone_e164):
            logger.info(f"[{phone}] Skipping — contact is opted out")
            return

        # 1. Get or create contact
        contact = get_contact_by_phone(phone_e164)

        # 1.5 Attribute inbound reply to campaign if linked
        if contact:
            try:
                from reply_mode import get_contact_campaign
                linked_campaign_id = get_contact_campaign(contact["contact_id"])
                if linked_campaign_id:
                    from database import get_db as _get_db
                    with _get_db() as _conn:
                        _conn.execute(
                            "UPDATE campaigns SET replied = replied + 1 WHERE id = ?",
                            (linked_campaign_id,),
                        )
                    logger.debug(
                        "Campaign %s: reply attributed from %s",
                        linked_campaign_id, phone,
                    )
            except Exception as _attr_err:
                logger.debug("Campaign reply attribution skipped: %s", _attr_err)

        # 1.6 Apply CTWA ad attribution if pending
        if phone_e164 in _ctwa_pending:
            try:
                ctwa_data = _ctwa_pending.pop(phone_e164)
                # Re-fetch contact (may have been auto-created by handle_inbound)
                if not contact:
                    contact = get_contact_by_phone(phone_e164)
                if contact:
                    update_contact(contact["contact_id"], source=ctwa_data["source"])
                    add_tag(contact["contact_id"], f"ctwa:{ctwa_data.get('source_id', 'ad')}")
                    logger.info("[%s] CTWA attribution applied: %s", phone, ctwa_data["source"])
            except Exception as _ctwa_err:
                logger.debug("CTWA attribution failed: %s", _ctwa_err)

        # 2. If bot is off (human mode), just save the message silently
        if contact and not is_bot_active(contact["contact_id"]):
            save_message(contact["contact_id"], "inbound", text, wa_message_id=msg_id)
            logger.info(f"[{phone}] Bot off -- message saved for human")
            # Push real-time event to dashboard
            t = asyncio.create_task(ws_manager.broadcast({
                "type": "new_message",
                "contact_id": contact["contact_id"],
                "contact_name": contact.get("name", ""),
                "direction": "inbound",
                "content": text[:500],
                "sent_by": "customer",
            }))
            t.add_done_callback(_log_task_error)
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
            t_ws = asyncio.create_task(ws_manager.broadcast({
                "type": "handoff_triggered",
                "contact_id": contact_id or "",
                "contact_name": contact_name,
                "reason": handoff_result.get("reason", ""),
            }))
            t_ws.add_done_callback(_log_task_error)
            return

        # 5. Determine reply mode for this contact
        reply_mode_info = get_effective_reply_mode(contact_id) if contact_id else {"mode": "auto_ai", "source": "default", "campaign_id": None, "campaign_kb": ""}
        effective_mode = reply_mode_info["mode"]
        campaign_kb_text = reply_mode_info.get("campaign_kb", "")

        # Log inbound event
        log_event("message_received", contact_id=contact_id or "", metadata={"phone_suffix": phone[-4:] if len(phone) >= 4 else "", "reply_mode": effective_mode})

        # --- human_only mode: save message, don't generate AI reply ---
        if effective_mode == "human_only":
            if contact_id:
                save_message(contact_id, "inbound", text, wa_message_id=msg_id)
                memory_add_message(contact_id, "inbound", text)
            logger.info(f"[{phone}] Reply mode is human_only -- message saved, no AI reply")
            # Notify team
            if notify_phone:
                notification = (
                    f"New message from {contact_name or phone_e164} (human-only mode):\n\n"
                    f"\"{text[:200]}\"\n\nReply from the dashboard."
                )
                t = asyncio.create_task(send_whatsapp_message(notify_phone, notification))
                t.add_done_callback(_log_task_error)
            return

        # --- ai_draft mode: generate draft but don't send ---
        if effective_mode == "ai_draft":
            if contact_id:
                save_message(contact_id, "inbound", text, wa_message_id=msg_id)
                memory_add_message(contact_id, "inbound", text)

            async def draft_llm_call(messages):
                return await call_llm_safe(messages, tier="sonnet", phone=phone)

            try:
                from conversation import generate_ai_reply
                draft_text = await generate_ai_reply(
                    contact_id, text, config=config, campaign_kb=campaign_kb_text
                )
                save_draft(
                    contact_id, draft_text,
                    customer_message=text,
                    campaign_id=reply_mode_info.get("campaign_id", ""),
                )
                logger.info(f"[{phone}] AI draft generated (pending human approval): {draft_text[:60]}...")
                # Push draft_ready event to dashboard
                _contact_name = contact.get("name", "") if contact else ""
                t_ws = asyncio.create_task(ws_manager.broadcast({
                    "type": "draft_ready",
                    "contact_id": contact_id or "",
                    "contact_name": _contact_name,
                    "draft_preview": draft_text[:200],
                }))
                t_ws.add_done_callback(_log_task_error)
            except Exception as e:
                logger.error(f"[{phone}] AI draft generation failed: {e}")
                save_draft(
                    contact_id,
                    "[Draft generation failed. Please compose a reply manually.]",
                    customer_message=text,
                )

            # Notify team about pending draft
            if notify_phone:
                notification = (
                    f"AI Draft ready for {contact_name or phone_e164}:\n\n"
                    f"Customer: \"{text[:150]}\"\n\n"
                    f"Review and approve the draft from the dashboard."
                )
                t = asyncio.create_task(send_whatsapp_message(notify_phone, notification))
                t.add_done_callback(_log_task_error)
            return

        # --- auto_ai mode: normal AI response (with campaign KB if available) ---
        async def llm_call(messages):
            return await call_llm_safe(messages, tier="sonnet", phone=phone)

        response = await handle_inbound(
            phone_e164, text, llm_call, config=config, campaign_kb=campaign_kb_text
        )

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

        # Meter AI message usage
        try:
            increment_usage("default", "ai_messages")
        except Exception:
            pass

        log_event("ai_reply_generated", contact_id=contact_id or "")
        await send_whatsapp_message(phone, response)
        log_event("message_sent", contact_id=contact_id or "")
        # Push real-time events to dashboard
        contact_name = contact.get("name", "") if contact else ""
        t_ws1 = asyncio.create_task(ws_manager.broadcast({
            "type": "new_message",
            "contact_id": contact_id or "",
            "contact_name": contact_name,
            "direction": "inbound",
            "content": text[:500],
            "sent_by": "customer",
        }))
        t_ws1.add_done_callback(_log_task_error)
        t_ws2 = asyncio.create_task(ws_manager.broadcast({
            "type": "new_message",
            "contact_id": contact_id or "",
            "contact_name": contact_name,
            "direction": "outbound",
            "content": response[:500],
            "sent_by": "bot",
        }))
        t_ws2.add_done_callback(_log_task_error)

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


_MIME_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/gif": "gif", "video/mp4": "mp4", "video/3gpp": "3gp",
    "application/pdf": "pdf", "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls", "text/plain": "txt",
}


def _mime_to_ext(mime: str) -> str:
    return _MIME_EXT.get(mime, "bin")


async def _handle_media_message(
    phone: str, media_id: str, media_type: str, msg_id: str, caption: str = ""
):
    """
    Handle inbound image / video / document / sticker messages.

    1. Download from WhatsApp CDN
    2. Store encrypted in data/media/{contact_id}/
    3. Save message record with content_type and media path
    4. Treat caption (if any) as a text message for AI response
    """
    try:
        phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
        contact = get_contact_by_phone(phone_e164)
        if not contact:
            logger.debug(f"[{phone}] Media from unknown contact — ignoring")
            return

        contact_id = contact["contact_id"]

        # Download media
        try:
            media_bytes, mime_type = await download_whatsapp_media(media_id)
        except Exception as e:
            logger.error(f"[{phone}] Media download failed: {e}")
            return

        # Store media file
        media_dir = DATA_DIR / "media" / contact_id
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = _mime_to_ext(mime_type)
        filename = f"{msg_id}.{ext}"
        media_path = media_dir / filename
        try:
            from encryption import encrypt_data
            encrypted_bytes = encrypt_data(phone_e164, media_bytes.hex())
            media_path.write_bytes(encrypted_bytes)
        except Exception as enc_err:
            # SECURITY: Log loudly — never silently store unencrypted PII
            logger.error(
                "[%s] Media encryption FAILED — storing encrypted placeholder only: %s",
                phone, enc_err,
            )
            # Store a placeholder instead of raw unencrypted media
            media_path.write_bytes(b"ENCRYPTION_FAILED:media_not_stored")

        # Save message record
        text_content = caption if caption else f"[{media_type.title()} message]"
        save_message(
            contact_id, "inbound", text_content,
            wa_message_id=msg_id,
        )

        logger.info(f"[{phone}] {media_type} message saved ({len(media_bytes)} bytes)")

        # If there's a caption, treat it as a text message for AI
        if caption:
            await _handle_text_message(phone, caption, msg_id)
        else:
            # Just notify dashboard
            asyncio.create_task(ws_manager.broadcast({
                "type": "new_message",
                "contact_id": contact_id,
                "contact_name": contact.get("name", ""),
                "direction": "inbound",
                "content": text_content,
                "sent_by": "customer",
                "media_type": media_type,
            }))

    except Exception as e:
        logger.error(f"[{phone}] Media message handling failed: {e}", exc_info=True)


# ====================================================================
#  DASHBOARD API — OVERVIEW
# ====================================================================

# ─────────────────────────────────────────────────────────────────────
#  Demo reset — wipes & reseeds the Bloom Interiors demo dataset.
#  Designed so a salesperson can reset state in one click before each
#  prospect demo, without touching the terminal.
#
#  Auth: requires a valid session token / API key (same as other admin
#  endpoints) AND the workspace must be the default demo workspace.
#  Disabled in production unless NAZAR_DEMO_MODE=1 is set in env.
# ─────────────────────────────────────────────────────────────────────
@app.post("/api/admin/reset-demo")
async def api_admin_reset_demo(request: Request):
    """
    Wipe and reseed the demo dataset (contacts, conversations, KB,
    templates, campaigns, analytics) by invoking seed_demo.py and
    demo_polish.py as subprocesses. Returns the combined log.

    Safety:
      - Requires a valid auth token (session or API key).
      - Refuses to run unless NAZAR_DEMO_MODE=1 (set in .env).
      - Holds a process-wide lock so only one reset runs at a time.
    """
    ctx = _check_api_key(request)

    if os.getenv("NAZAR_DEMO_MODE", "0") not in ("1", "true", "yes"):
        raise HTTPException(
            status_code=403,
            detail=(
                "Demo reset is disabled. Set NAZAR_DEMO_MODE=1 in your .env "
                "to enable this endpoint."
            ),
        )

    # Process-wide lock to prevent concurrent resets.
    global _demo_reset_lock
    try:
        lock = _demo_reset_lock
    except NameError:
        lock = asyncio.Lock()
        globals()["_demo_reset_lock"] = lock

    if lock.locked():
        raise HTTPException(status_code=409, detail="Reset already in progress.")

    async with lock:
        import subprocess
        root = Path(__file__).parent
        py = sys.executable or "python3"
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        steps = [
            ("seed_demo.py", [py, "seed_demo.py"]),
            ("demo_polish.py", [py, "demo_polish.py"]),
        ]

        log_chunks: list[str] = []
        ok = True
        for label, cmd in steps:
            log_chunks.append(f"\n── Running {label} ──")
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(root),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                # Cap output collection to avoid runaway memory.
                try:
                    stdout, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=180
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    log_chunks.append(f"[{label}] TIMEOUT after 180s")
                    ok = False
                    break
                out = (stdout or b"").decode(errors="replace")
                # Keep last ~6 KB of output per step
                log_chunks.append(out[-6000:])
                if proc.returncode != 0:
                    log_chunks.append(f"[{label}] exited with code {proc.returncode}")
                    ok = False
                    # demo_polish failures are non-fatal — keep going.
                    if label == "seed_demo.py":
                        break
            except Exception as e:
                log_chunks.append(f"[{label}] failed: {e!r}")
                ok = False
                break

        full_log = "\n".join(log_chunks)
        return {
            "ok": ok,
            "workspace_id": ctx.get("workspace_id", "default"),
            "log": full_log,
            "completed_at": datetime.now(IST).isoformat(),
        }


@app.get("/api/admin/reset-demo/status")
async def api_admin_reset_demo_status(request: Request):
    """Lightweight status check for the demo reset endpoint."""
    _check_api_key(request)
    enabled = os.getenv("NAZAR_DEMO_MODE", "0") in ("1", "true", "yes")
    in_progress = False
    try:
        in_progress = _demo_reset_lock.locked()  # type: ignore[name-defined]
    except NameError:
        in_progress = False
    return {"enabled": enabled, "in_progress": in_progress}


@app.get("/api/billing/trial-status")
async def api_trial_status(request: Request):
    """Check if the workspace trial has expired. Used by frontend paywall."""
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    from billing import get_trial_days_remaining
    sub = get_subscription(workspace_id)
    if not sub:
        return {"active": False, "status": "none", "trial_expired": True}

    active = is_subscription_active(workspace_id)
    trial_days = get_trial_days_remaining(workspace_id)
    return {
        "active": active,
        "status": sub.get("status", "none"),
        "plan_id": sub.get("plan_id", "starter"),
        "trial_expired": sub.get("status") == "trialing" and not active,
        "trial_days_remaining": trial_days,
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
    }


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
async def api_list_contacts(
    request: Request,
    stage: str = None,
    tag: str = None,
    assigned_to: str = None,
    search: str = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
):
    _check_api_key(request)
    contacts = list_contacts(stage=stage, tag=tag, assigned_to=assigned_to)

    # Search filter
    if search:
        sq = search.lower()
        contacts = [
            c for c in contacts
            if sq in (c.get("name") or "").lower()
            or sq in (c.get("phone") or "").lower()
            or sq in (c.get("company") or "").lower()
        ]

    # Sort
    reverse = sort_order.lower() != "asc"
    sort_field_map = {
        "name": lambda c: (c.get("name") or "").lower(),
        "updated_at": lambda c: c.get("last_contacted_at") or c.get("created_at") or "",
        "lead_score": lambda c: c.get("lead_score") or 0,
        "deal_value": lambda c: c.get("deal_value") or 0,
        "created_at": lambda c: c.get("created_at") or "",
    }
    key_fn = sort_field_map.get(sort_by, sort_field_map["updated_at"])
    try:
        contacts.sort(key=key_fn, reverse=reverse)
    except Exception:
        pass

    # Pagination
    total = len(contacts)
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size
    page_contacts = contacts[start:end]

    return {
        "contacts": page_contacts,
        "total": total,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "has_next": end < total,
            "has_prev": page > 1,
        },
    }


@app.post("/api/contacts")
async def api_create_contact(request: Request):
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    _check_billing_limit(ctx, "contacts")
    try:
        body_raw = await request.json()
        body = CreateContactRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    try:
        contact = create_contact(
            name=body.name,
            phone=body.phone,
            company=body.company,
            source=body.source,
            assigned_to=body.assigned_to,
            tags=body.tags,
        )
        if body.deal_value is not None:
            contact = update_contact(contact["contact_id"], deal_value=body.deal_value)
        # Meter contact usage
        increment_usage(ctx.get("workspace_id", "default"), "contacts")
        # Audit + WebSocket
        actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
        log_audit("contact.created", "contact", contact["contact_id"], actor_id=actor_id,
                  details={"source": body.source})
        asyncio.create_task(ws_manager.broadcast({
            "type": "contact_updated",
            "contact_id": contact["contact_id"],
            "fields": {"created": True, "name": contact.get("name", "")},
        }))
        asyncio.create_task(webhook_dispatcher_mod.dispatch("contact.created", {
            "contact_id": contact["contact_id"],
            "name": contact.get("name", ""),
            "stage": contact.get("pipeline_stage", "New"),
        }))
        return {"contact": contact}
    except ValueError as e:
        raise HTTPException(400, str(e))


# NOTE: Static paths like /export and /merge MUST be defined BEFORE
# parameterized paths like /{contact_id} to avoid FastAPI capturing
# "export" or "merge" as a contact_id.

@app.get("/api/contacts/export")
async def api_export_contacts_route(request: Request, stage: str = None, tag: str = None):
    """
    Export contacts as CSV.

    Query params:
      - stage: filter by pipeline stage
      - tag: filter by tag

    Returns: CSV file download
    """
    _check_api_key(request)
    import csv as _csv
    import io as _io

    contacts = list_contacts(stage=stage, tag=tag)

    output = _io.StringIO()
    writer = _csv.writer(output)

    writer.writerow([
        "Name", "Phone", "Company", "Pipeline Stage", "Lead Score",
        "Deal Value", "Tags", "Source", "Assigned To", "Notes",
        "Total Messages", "Last Contacted", "Last Replied", "Created At",
    ])

    for c in contacts:
        writer.writerow([
            c.get("name", ""),
            c.get("phone", ""),
            c.get("company", ""),
            c.get("pipeline_stage", ""),
            c.get("lead_score", 0),
            c.get("deal_value", 0),
            "; ".join(c.get("tags", [])),
            c.get("source", ""),
            c.get("assigned_to", ""),
            c.get("notes", ""),
            c.get("total_messages", 0),
            c.get("last_contacted_at", ""),
            c.get("last_replied_at", ""),
            c.get("created_at", ""),
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=nazar_contacts_{datetime.now(IST).strftime('%Y%m%d')}.csv",
        },
    )


@app.get("/api/contacts/{contact_id}")
async def api_get_contact(contact_id: str, request: Request):
    _check_api_key(request)
    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
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


@app.post("/api/contacts/merge")
async def api_merge_contacts(request: Request):
    """
    Merge two duplicate contacts into one.

    Body:
      - primary_id: str — the contact to keep
      - secondary_id: str — the contact to merge into primary (will be deleted)

    Merges:
      - All messages from secondary → primary
      - Tags combined
      - Notes appended
      - Higher lead_score kept
      - Higher deal_value kept
    """
    ctx = _check_api_key(request)
    body = await request.json()
    primary_id = body.get("primary_id", "")
    secondary_id = body.get("secondary_id", "")

    if not primary_id or not secondary_id:
        raise HTTPException(400, "primary_id and secondary_id are required")
    if primary_id == secondary_id:
        raise HTTPException(400, "Cannot merge a contact with itself")

    try:
        primary = get_contact(primary_id)
        secondary = get_contact(secondary_id)
    except FileNotFoundError:
        raise HTTPException(404, "One or both contacts not found")

    from database import get_db as _merge_get_db

    with _merge_get_db() as conn:
        # Move all messages from secondary to primary
        conn.execute(
            "UPDATE messages SET contact_id = ? WHERE contact_id = ?",
            (primary_id, secondary_id),
        )

        # Merge tags
        primary_tags = set(primary.get("tags", []))
        secondary_tags = set(secondary.get("tags", []))
        merged_tags = list(primary_tags | secondary_tags)

        # Merge notes
        primary_notes = primary.get("notes", "")
        secondary_notes = secondary.get("notes", "")
        merged_notes = primary_notes
        if secondary_notes:
            merged_notes += f"\n\n--- Merged from {secondary.get('name', secondary_id)} ---\n{secondary_notes}"

        # Take higher values
        merged_score = max(primary.get("lead_score", 0), secondary.get("lead_score", 0))
        merged_deal = max(primary.get("deal_value", 0), secondary.get("deal_value", 0))
        merged_messages = (primary.get("total_messages", 0) + secondary.get("total_messages", 0))

        # Update primary
        update_contact(
            primary_id,
            tags=merged_tags,
            notes=merged_notes,
            lead_score=merged_score,
            deal_value=merged_deal,
            total_messages=merged_messages,
        )

        # Delete secondary
        conn.execute("DELETE FROM contacts WHERE id = ?", (secondary_id,))

    # Audit
    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
    log_audit("contact.merged", "contact", primary_id, actor_id=actor_id,
              details={"merged_from": secondary_id, "secondary_name": secondary.get("name", "")})

    return {
        "ok": True,
        "primary": get_contact(primary_id),
        "merged_from": secondary_id,
    }


@app.post("/api/contacts/import")
async def api_import_contacts(request: Request):
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    try:
        body_raw = await request.json()
        body = ImportContactsRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    result = import_contacts_csv(body.csv)
    # Update contact count in usage
    contacts = list_contacts()
    set_usage(ctx.get("workspace_id", "default"), "contacts", len(contacts))
    return result


# ====================================================================
#  DASHBOARD API — CONVERSATIONS
# ====================================================================

@app.get("/api/conversations")
async def api_list_conversations(
    request: Request,
    status: str = None,
    page: int = 1,
    page_size: int = 50,
):
    _check_api_key(request)

    # Optimized: single DB query to get contacts + latest message + handoff state
    # instead of O(N) queries per contact
    from database import get_db as _conv_get_db

    now = datetime.now(IST)

    with _conv_get_db() as conn:
        # Single query: join contacts with their latest message
        rows = conn.execute("""
            SELECT
                c.id AS contact_id,
                c.name,
                c.phone,
                c.pipeline_stage AS stage,
                c.tags,
                c.lead_score,
                c.total_messages AS message_count,
                c.last_replied_at,
                c.last_contacted_at,
                m.content AS last_message_content,
                m.timestamp AS last_message_time,
                m.direction AS last_message_direction,
                m.sent_by AS last_message_sender,
                COALESCE(h.bot_active, 1) AS bot_active
            FROM contacts c
            LEFT JOIN (
                SELECT contact_id, content, timestamp, direction, sent_by,
                       ROW_NUMBER() OVER (PARTITION BY contact_id ORDER BY timestamp DESC) AS rn
                FROM messages
            ) m ON m.contact_id = c.id AND m.rn = 1
            LEFT JOIN handoff_states h ON h.contact_id = c.id
            WHERE c.workspace_id = 'default'
            ORDER BY COALESCE(m.timestamp, c.last_replied_at, c.created_at) DESC
        """).fetchall()

    conversations = []
    for row in rows:
        d = dict(row)
        last_inbound = d.get("last_replied_at") or ""

        # Inline window computation (avoid function call overhead)
        window_open = False
        hours_remaining = 0
        if last_inbound:
            try:
                last_dt = datetime.fromisoformat(last_inbound)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=IST)
                remaining = (last_dt + timedelta(hours=24) - now).total_seconds()
                window_open = remaining > 0
                hours_remaining = round(max(0, remaining / 3600), 2)
            except Exception:
                pass

        import json as _json
        tags = d.get("tags", "[]")
        if isinstance(tags, str):
            try:
                tags = _json.loads(tags)
            except Exception:
                tags = []

        conversations.append({
            "contact_id": d["contact_id"],
            "name": d.get("name") or "Unknown",
            "phone": d.get("phone") or "",
            "stage": d.get("stage") or "New",
            "tags": tags,
            "lead_score": d.get("lead_score") or 0,
            "last_message": (d.get("last_message_content") or "")[:100],
            "last_time": d.get("last_message_time") or d.get("last_replied_at") or "",
            "last_direction": d.get("last_message_direction") or None,
            "last_sender": d.get("last_message_sender") or None,
            "bot_mode": bool(d.get("bot_active", 1)),
            "message_count": d.get("message_count") or 0,
            "window_open": window_open,
            "hours_remaining": hours_remaining,
        })

    # Pagination
    total = len(conversations)
    page_size = min(max(page_size, 1), 200)
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "conversations": conversations[start:end],
        "total": total,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
    }


@app.get("/api/conversations/search")
async def api_search_conversations(request: Request, q: str = "", limit: int = 50):
    """Full-text search across message content."""
    _check_api_key(request)
    if not q or len(q.strip()) < 2:
        raise HTTPException(400, "Search query must be at least 2 characters")

    from database import get_db as _search_get_db

    with _search_get_db() as conn:
        rows = conn.execute(
            """SELECT m.contact_id, m.content, m.direction, m.timestamp, m.sent_by,
                      c.name AS contact_name, c.phone AS contact_phone
               FROM messages m
               JOIN contacts c ON c.id = m.contact_id
               WHERE m.content LIKE ? AND m.workspace_id = 'default'
               ORDER BY m.timestamp DESC
               LIMIT ?""",
            (f"%{q}%", min(limit, 200)),
        ).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        results.append({
            "contact_id": d["contact_id"],
            "contact_name": d.get("contact_name", ""),
            "contact_phone": d.get("contact_phone", ""),
            "content": d["content"],
            "direction": d["direction"],
            "sent_by": d.get("sent_by", ""),
            "timestamp": d["timestamp"],
        })

    return {"results": results, "count": len(results), "query": q}


@app.get("/api/conversations/{contact_id}")
async def api_get_conversation(contact_id: str, request: Request, days: int = 7):
    _check_api_key(request)
    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")
    messages = get_conversation_history(contact_id, days=days)
    memory_summary = get_customer_summary(contact_id)
    reply_mode_info = get_effective_reply_mode(contact_id)
    draft = get_draft(contact_id)
    window = _compute_service_window(contact)
    return {
        "contact": contact,
        "messages": messages,
        "memory": memory_summary,
        "bot_mode": is_bot_active(contact_id),
        "handoff_state": get_contact_handoff_state(contact_id),
        "reply_mode": reply_mode_info,
        "pending_draft": draft,
        "service_window": window,
    }


@app.post("/api/conversations/{contact_id}/send")
async def api_send_message(contact_id: str, request: Request):
    """Send a message — works with or without WhatsApp configured."""
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    try:
        body_raw = await request.json()
        body = SendMessageRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    text = body.message

    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    phone = contact["phone"]

    # Check opt-out before sending
    phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
    if not can_message(phone_e164):
        raise HTTPException(400, "Contact has opted out. Cannot send message.")

    # Check 24h service window
    window = _compute_service_window(contact)
    window_warning = window.get("warning")

    wa_msg_id = ""
    wa_send_error = None

    # Try WhatsApp send if configured
    if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            result = await send_whatsapp_message(phone, text)
            if "error" in result:
                error_code = result["error"].get("code", 0)
                error_msg = result["error"].get("message", "Unknown error")
                # 131047 = re-engagement message (outside 24h window without template)
                if error_code == 131047:
                    wa_send_error = (
                        "WhatsApp rejected this message because the 24h customer service window "
                        "has closed. Use an approved template to re-initiate the conversation."
                    )
                    logger.warning(f"[{phone}] Free-form message rejected (131047): window closed")
                else:
                    wa_send_error = f"WhatsApp error [{error_code}]: {error_msg}"
            elif "messages" in result:
                wa_msg_id = result["messages"][0].get("id", "")
        except Exception as e:
            logger.warning(f"WhatsApp send failed (continuing locally): {e}")

    # Always save to conversation history (even if WA rejected it)
    save_message(contact_id, "outbound", text, sent_by="human", wa_message_id=wa_msg_id)
    memory_add_message(contact_id, "outbound", text)

    # Mark human responded if in handoff
    if not is_bot_active(contact_id):
        mark_human_responded(contact_id)

    update_contact(contact_id, last_contacted_at=datetime.now(IST).isoformat())

    log_event("message_sent", contact_id=contact_id)
    # Push real-time event
    asyncio.create_task(ws_manager.broadcast({
        "type": "new_message",
        "contact_id": contact_id,
        "contact_name": contact.get("name", ""),
        "direction": "outbound",
        "content": text[:500],
        "sent_by": "human",
    }))
    return {
        "ok": True,
        "wa_message_id": wa_msg_id,
        "whatsapp_sent": bool(wa_msg_id),
        "window_warning": window_warning,
        "wa_send_error": wa_send_error,
        "service_window": {
            "window_open": window["window_open"],
            "hours_remaining": window["hours_remaining"],
            "requires_template": window["requires_template"],
        },
    }


@app.post("/api/conversations/{contact_id}/send-interactive")
async def api_send_interactive(contact_id: str, request: Request):
    """
    Send a WhatsApp interactive message (buttons or list).

    Body:
      - type: "buttons" or "list"
      - body: str — main message body
      - buttons: list of {"id": "btn_1", "title": "Click"} (for type=buttons, max 3)
      - button_text: str — button label for list (for type=list)
      - sections: list of sections (for type=list)
      - header: str — optional header
      - footer: str — optional footer
    """
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    body = await request.json()

    msg_type = body.get("type", "buttons")
    body_text = body.get("body", "").strip()
    if not body_text:
        raise HTTPException(400, "body text is required")

    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    phone = contact["phone"]

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(503, "WhatsApp not configured")

    result = {}
    if msg_type == "buttons":
        buttons = body.get("buttons", [])
        if not buttons or len(buttons) > 3:
            raise HTTPException(400, "1-3 buttons required")
        result = await send_interactive_buttons(
            phone, body_text, buttons,
            header=body.get("header", ""),
            footer=body.get("footer", ""),
        )
    elif msg_type == "list":
        button_text = body.get("button_text", "View Options")
        sections = body.get("sections", [])
        if not sections:
            raise HTTPException(400, "At least one section required")
        result = await send_interactive_list(
            phone, body_text, button_text, sections,
            header=body.get("header", ""),
            footer=body.get("footer", ""),
        )
    else:
        raise HTTPException(400, "type must be 'buttons' or 'list'")

    wa_msg_id = ""
    if "messages" in result:
        wa_msg_id = result["messages"][0].get("id", "")

    # Save as outbound message
    preview = f"[Interactive {msg_type}] {body_text[:200]}"
    save_message(contact_id, "outbound", preview, sent_by="human", wa_message_id=wa_msg_id)

    return {"ok": True, "wa_message_id": wa_msg_id, "result": result}


@app.post("/api/conversations/{contact_id}/schedule")
async def api_schedule_message(contact_id: str, request: Request):
    """
    Schedule a message to be sent at a specific time.

    Body:
      - message: str — the message text
      - send_at: str — ISO datetime when to send
    """
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    body = await request.json()
    message_text = body.get("message", "").strip()
    send_at = body.get("send_at", "")

    if not message_text:
        raise HTTPException(400, "message is required")
    if not send_at:
        raise HTTPException(400, "send_at is required (ISO datetime)")

    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    # Schedule via background job
    async def _scheduled_send_worker(job_id: str, params: dict, update_progress):
        import asyncio as _asyncio
        target_time = datetime.fromisoformat(params["send_at"])
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=IST)
        now = datetime.now(IST)
        delay = (target_time - now).total_seconds()
        if delay > 0:
            await _asyncio.sleep(delay)

        phone = params["phone"]
        text = params["message"]
        cid = params["contact_id"]

        wa_msg_id = ""
        if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
            try:
                result = await send_whatsapp_message(phone, text)
                if "messages" in result:
                    wa_msg_id = result["messages"][0].get("id", "")
            except Exception as e:
                logger.warning(f"Scheduled message send failed: {e}")

        save_message(cid, "outbound", text, sent_by="scheduled", wa_message_id=wa_msg_id)
        update_progress(job_id, 1, 1, 0)

        await ws_manager.broadcast({
            "type": "new_message",
            "contact_id": cid,
            "contact_name": params.get("contact_name", ""),
            "direction": "outbound",
            "content": text[:500],
            "sent_by": "scheduled",
        })

    job_id = await job_queue.enqueue(
        "scheduled_message",
        {
            "contact_id": contact_id,
            "phone": contact["phone"],
            "message": message_text,
            "send_at": send_at,
            "contact_name": contact.get("name", ""),
        },
        _scheduled_send_worker,
    )

    return {
        "ok": True,
        "job_id": job_id,
        "scheduled_at": send_at,
        "contact_id": contact_id,
    }


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
    stats = get_handoff_stats()
    # Count followups and merge into stats
    contacts = list_contacts()
    now = datetime.now(IST)
    followup_count = 0
    for c in contacts:
        if c["pipeline_stage"] in ("Won", "Lost"):
            continue
        last_contact = c.get("last_contacted_at") or c.get("last_replied_at") or ""
        if not last_contact:
            continue
        try:
            days_since = (now - datetime.fromisoformat(last_contact)).days
            if days_since >= 2:
                followup_count += 1
        except Exception:
            pass
    stats["followup_count"] = followup_count
    return stats


@app.post("/api/handoffs/{contact_id}/resume")
async def api_resume_bot(contact_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    reason = body.get("reason", "Resumed from dashboard")
    entry = resume_bot(contact_id, resumed_by="manual", reason=reason)
    return {"ok": True, "handoff_state": entry}


# ====================================================================
#  DASHBOARD API — REPLY MODES & AI DRAFTS
# ====================================================================

@app.get("/api/reply-modes/{contact_id}")
async def api_get_reply_mode(contact_id: str, request: Request):
    """Get the effective reply mode for a contact."""
    _check_api_key(request)
    return get_effective_reply_mode(contact_id)


@app.put("/api/reply-modes/{contact_id}")
async def api_set_reply_mode(contact_id: str, request: Request):
    """Set reply mode for a contact (overrides campaign/default)."""
    _check_api_key(request)
    body = await request.json()
    mode = body.get("mode", "")
    if mode not in VALID_MODES:
        raise HTTPException(400, f"Invalid mode. Must be one of: {', '.join(VALID_MODES)}")
    entry = set_contact_reply_mode(contact_id, mode, set_by="manual")
    return {"ok": True, "reply_mode": entry, "effective": get_effective_reply_mode(contact_id)}


@app.delete("/api/reply-modes/{contact_id}")
async def api_clear_reply_mode(contact_id: str, request: Request):
    """Remove custom reply mode for a contact (reverts to campaign/default)."""
    _check_api_key(request)
    clear_contact_reply_mode(contact_id)
    return {"ok": True, "effective": get_effective_reply_mode(contact_id)}


@app.get("/api/drafts")
async def api_list_drafts(request: Request):
    """Get all pending AI drafts for review."""
    _check_api_key(request)
    drafts = get_all_pending_drafts()
    # Enrich with contact info
    for d in drafts:
        try:
            contact = get_contact(d["contact_id"])
            d["contact_name"] = contact.get("name", "Unknown") if contact else "Unknown"
            d["contact_phone"] = contact.get("phone", "") if contact else ""
        except Exception:
            d["contact_name"] = "Unknown"
            d["contact_phone"] = ""
    return {"drafts": drafts, "count": len(drafts)}


@app.get("/api/drafts/{contact_id}")
async def api_get_draft(contact_id: str, request: Request):
    """Get pending AI draft for a specific contact."""
    _check_api_key(request)
    draft = get_draft(contact_id)
    if not draft:
        raise HTTPException(404, "No pending draft for this contact")
    return {"draft": draft}


@app.post("/api/drafts/{contact_id}/approve")
async def api_approve_draft(contact_id: str, request: Request):
    """
    Approve an AI draft and send it to the customer.
    
    Body:
      - edited_text: (optional) Edited version of the draft to send instead
    """
    _check_api_key(request)
    body = await request.json()
    edited_text = body.get("edited_text", "")

    draft = approve_draft(contact_id, edited_text=edited_text)
    if not draft:
        raise HTTPException(404, "No pending draft to approve")

    final_text = draft["final_text"]

    # Send the approved message
    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    phone = contact["phone"]
    wa_msg_id = ""

    if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
        try:
            result = await send_whatsapp_message(phone, final_text)
            if "messages" in result:
                wa_msg_id = result["messages"][0].get("id", "")
        except Exception as e:
            logger.warning(f"WhatsApp send failed for approved draft: {e}")

    save_message(contact_id, "outbound", final_text, sent_by="bot-approved", wa_message_id=wa_msg_id)
    from customer_memory import add_message as memory_add_message
    memory_add_message(contact_id, "outbound", final_text)

    log_event("draft_approved", contact_id=contact_id)
    log_audit("draft.approved", "draft", contact_id,
              details={"edited": bool(edited_text)})
    asyncio.create_task(webhook_dispatcher_mod.dispatch("draft.approved", {
        "contact_id": contact_id, "edited": bool(edited_text),
    }))
    return {"ok": True, "sent": final_text, "wa_message_id": wa_msg_id}


@app.post("/api/drafts/{contact_id}/reject")
async def api_reject_draft(contact_id: str, request: Request):
    """Reject an AI draft (agent will compose their own reply)."""
    _check_api_key(request)
    draft = reject_draft(contact_id)
    if not draft:
        raise HTTPException(404, "No pending draft to reject")
    return {"ok": True}


@app.post("/api/drafts/{contact_id}/regenerate")
async def api_regenerate_draft(contact_id: str, request: Request):
    """Regenerate the AI draft for a contact."""
    _check_api_key(request)
    existing = get_draft(contact_id)
    customer_message = existing.get("customer_message", "") if existing else ""
    campaign_id = existing.get("campaign_id", "") if existing else ""

    if not customer_message:
        raise HTTPException(400, "No customer message to regenerate draft for")

    campaign_kb_text = get_campaign_kb(campaign_id) if campaign_id else ""

    try:
        from conversation import generate_ai_reply
        config = _load_config()
        new_draft = await generate_ai_reply(
            contact_id, customer_message, config=config, campaign_kb=campaign_kb_text
        )
        entry = save_draft(contact_id, new_draft, customer_message=customer_message, campaign_id=campaign_id)
        return {"ok": True, "draft": entry}
    except Exception as e:
        raise HTTPException(500, f"Draft regeneration failed: {str(e)}")


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
    ctx = _check_api_key(request)
    try:
        body_raw = await request.json()
        body = MovePipelineRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    try:
        contact = move_stage(contact_id, body.stage)
        # Mark manual override so AI won't reclassify
        update_contact(contact_id, manual_stage_override=1)
        actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
        log_audit("contact.stage_changed", "contact", contact_id, actor_id=actor_id,
                  details={"new_stage": body.stage, "manual_override": True})
        asyncio.create_task(webhook_dispatcher_mod.dispatch("contact.stage_changed", {
            "contact_id": contact_id,
            "stage": body.stage,
        }))
        asyncio.create_task(ws_manager.broadcast({
            "type": "contact_updated",
            "contact_id": contact_id,
            "fields": {"pipeline_stage": body.stage},
        }))
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


@app.patch("/api/pipeline/{contact_id}/auto-classify")
async def api_enable_auto_classify(contact_id: str, request: Request):
    """Clear manual stage override so AI can reclassify this contact."""
    ctx = _check_api_key(request)
    try:
        update_contact(contact_id, manual_stage_override=0)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
    log_audit("contact.auto_classify_enabled", "contact", contact_id, actor_id=actor_id)
    return {"ok": True, "message": "AI auto-classification re-enabled for this contact"}





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

    # Also sync the Quick Edit content into the structured KB so it participates
    # in RAG queries alongside uploaded documents.
    try:
        docs = kb_manager.list_documents(scope="global")
        legacy_doc = next((d for d in docs if d.get("title") == "__quick_edit__"), None)
        if legacy_doc:
            # Delete old and re-add with updated content
            kb_manager.delete_document(legacy_doc["id"])
        kb_manager.add_document(
            title="__quick_edit__",
            content=content,
            doc_type="text",
            scope="global",
        )
    except Exception as e:
        logger.warning("Failed to sync Quick Edit to structured KB: %s", e)

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
    try:
        body_raw = await request.json()
        body = CreateTemplateRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    try:
        template = create_template(
            name=body.name,
            body=body.body,
            category=body.category,
            variables=body.variables or [],
            language=body.language,
            description=body.description or "",
            header=body.header,
            footer=body.footer or "",
            buttons=body.buttons or [],
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
#  DASHBOARD API — META TEMPLATE SYNC
# ====================================================================

@app.get("/api/templates/meta/status")
async def api_meta_template_config(request: Request):
    """Check if Meta template sync is configured."""
    _check_api_key(request)
    return {
        "configured": is_meta_configured(),
        "waba_id_set": bool(os.environ.get("WA_BUSINESS_ACCOUNT_ID", "")),
        "access_token_set": bool(os.environ.get("WA_ACCESS_TOKEN", "")),
    }


@app.post("/api/templates/{template_id}/submit-to-meta")
async def api_submit_template_to_meta(template_id: str, request: Request):
    """
    Submit a template to Meta's WhatsApp Template Management API for approval.

    The template must exist locally. After submission, Meta reviews it
    (usually takes minutes to hours). Status updates arrive via webhook
    or can be polled via the sync endpoint.
    """
    ctx = _check_api_key(request)
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    result = await submit_template_to_meta(template)

    if result["success"]:
        # Update local template with Meta's response
        update_fields = {"approval_status": result["status"]}
        if result.get("meta_id"):
            update_fields["meta_template_id"] = result["meta_id"]
        update_template(template_id, **update_fields)

        actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
        log_audit("template.submitted_to_meta", "template", template_id,
                  actor_id=actor_id,
                  details={"meta_id": result.get("meta_id"), "status": result["status"]})

    return result


@app.get("/api/templates/{template_id}/meta-status")
async def api_get_template_meta_status(template_id: str, request: Request):
    """
    Fetch the current approval status of a template from Meta's API.
    Useful for polling status after submission.
    """
    _check_api_key(request)
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    meta_status = await get_meta_template_status(template["name"])
    if not meta_status:
        return {
            "found_on_meta": False,
            "local_status": template.get("approval_status", "pending"),
            "message": "Template not found on Meta. Submit it first.",
        }

    # Auto-update local status if different
    if meta_status["status"] != template.get("approval_status"):
        update_template(template_id, approval_status=meta_status["status"])

    return {
        "found_on_meta": True,
        "meta_status": meta_status,
        "local_status": template.get("approval_status"),
        "synced": meta_status["status"] == template.get("approval_status"),
    }


@app.post("/api/templates/meta/sync")
async def api_sync_meta_templates(request: Request):
    """
    Sync all local template statuses with Meta's API.
    Fetches all templates from Meta and updates local approval_status.
    """
    ctx = _check_api_key(request)
    result = await sync_all_templates()

    if result.get("updated", 0) > 0:
        actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
        log_audit("templates.synced_with_meta", "template", "all",
                  actor_id=actor_id,
                  details={"synced": result.get("synced"), "updated": result.get("updated")})

    return result


# ====================================================================
#  DASHBOARD API — 24H CUSTOMER SERVICE WINDOW
# ====================================================================

@app.get("/api/contacts/{contact_id}/window")
async def api_contact_service_window(contact_id: str, request: Request):
    """
    Get the 24h customer service window status for a contact.

    WhatsApp rules:
      - Customer messages you → opens a 24h free-form messaging window
      - After 24h of no inbound → only pre-approved templates can be sent
      - Each new inbound message resets the 24h timer

    Returns:
      - window_open: bool (can you send free-form messages?)
      - expires_at: ISO datetime when the window closes (null if closed)
      - hours_remaining: float (0 if closed)
      - last_inbound_at: ISO datetime of last customer message
      - requires_template: bool (opposite of window_open)
    """
    _check_api_key(request)
    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    return _compute_service_window(contact)


@app.get("/api/contacts/windows")
async def api_all_service_windows(request: Request, stage: str = None):
    """
    Get 24h service window status for all contacts (or filtered by stage).
    Useful for the campaign wizard to show which contacts can receive
    free-form messages vs. which require templates.
    """
    _check_api_key(request)
    contacts = list_contacts(stage=stage)
    now = datetime.now(IST)

    window_open = 0
    window_closed = 0
    results = []

    for c in contacts:
        w = _compute_service_window(c, now=now)
        if w["window_open"]:
            window_open += 1
        else:
            window_closed += 1
        results.append({
            "contact_id": c["contact_id"],
            "name": c.get("name", ""),
            "phone": c.get("phone", ""),
            "window_open": w["window_open"],
            "hours_remaining": w["hours_remaining"],
            "last_inbound_at": w["last_inbound_at"],
        })

    return {
        "contacts": results,
        "summary": {
            "window_open": window_open,
            "window_closed": window_closed,
            "total": len(results),
        },
    }


def _compute_service_window(contact: dict, now: datetime = None) -> dict:
    """
    Compute the 24h customer service window status for a contact.
    Delegates to service_window module for centralized logic.
    """
    return sw_compute_window(contact, now)


# ====================================================================
#  CAMPAIGN AUDIENCE WINDOW ANALYSIS
# ====================================================================

@app.get("/api/campaigns/audience-analysis")
async def api_campaign_audience_analysis(
    request: Request,
    stage: str = None,
    tag: str = None,
):
    """
    Analyze campaign target contacts by 24h service window status.

    Campaigns ALWAYS use template messages (required by Meta for business-initiated
    conversations). This endpoint helps users understand which contacts have active
    windows (for context) and which require templates (all of them, for campaigns).

    Returns:
      - summary: { open_count, closed_count, total }
      - contacts: list with window status per contact
    """
    _check_api_key(request)
    contacts = list_contacts(stage=stage, tag=tag)

    results = []
    open_count = 0
    closed_count = 0

    for c in contacts:
        w = _compute_service_window(c)
        if w["window_open"]:
            open_count += 1
        else:
            closed_count += 1
        results.append({
            "contact_id": c["contact_id"],
            "name": c.get("name", ""),
            "phone": c.get("phone", ""),
            "stage": c.get("pipeline_stage", ""),
            "window_open": w["window_open"],
            "hours_remaining": w["hours_remaining"],
            "last_inbound_at": w.get("last_inbound_at"),
        })

    return {
        "contacts": results,
        "summary": {
            "open_count": open_count,
            "closed_count": closed_count,
            "total": len(results),
        },
        "info": (
            "Campaigns always use Meta-approved template messages regardless of window status. "
            "Templates can reach contacts even outside the 24h window."
        ),
    }


# ====================================================================
#  DASHBOARD API — CAMPAIGNS
# ====================================================================

@app.get("/api/campaigns")
async def api_list_campaigns(request: Request, page: int = 1, page_size: int = 20):
    """List all campaigns with stats (paginated)."""
    _check_api_key(request)
    all_campaigns = get_campaign_history(limit=500)
    stats = get_campaign_stats()

    total = len(all_campaigns)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "campaigns": all_campaigns[start:end],
        "stats": stats,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "has_next": end < total,
            "has_prev": page > 1,
        },
    }


@app.get("/api/campaigns/{campaign_id}")
async def api_get_campaign(campaign_id: str, request: Request):
    """Get a single campaign by ID."""
    _check_api_key(request)
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return {"campaign": campaign}


@app.post("/api/campaigns")
async def api_create_campaign(request: Request):
    """
    Create and execute a campaign via background job queue.

    Returns immediately with a campaign record and job_id.
    The actual sending happens asynchronously — progress is pushed via WebSocket.

    Body:
      - name: Campaign name
      - template_id: Template to send
      - filter_stage: (optional) Pipeline stage filter
      - filter_tag: (optional) Tag filter
      - contact_ids: (optional) Specific contact IDs to target
      - scheduled_at: (optional) ISO datetime to schedule
      - reply_mode: (optional) "auto_ai" | "human_only" | "ai_draft"
      - campaign_kb: (optional) Campaign-specific knowledge base text
    """
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    _check_billing_limit(ctx, "campaigns")
    workspace_id = ctx.get("workspace_id", "default")
    try:
        body_raw = await request.json()
        body = CreateCampaignRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))

    campaign_name = body.name
    template_id = body.template_id
    filter_stage = body.filter_stage
    filter_tag = body.filter_tag
    contact_ids = body.contact_ids or []
    group_ids = body_raw.get("group_ids") or []
    scheduled_at = body.scheduled_at
    reply_mode = body.reply_mode
    campaign_kb_text = body.campaign_kb or ""
    header_image_url = body_raw.get("header_image_url", "")

    # Load template
    template = get_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    if template.get("approval_status") != "approved":
        raise HTTPException(400, "Template must be approved before sending")

    # Get target contacts — group_ids take precedence, then contact_ids, then filters
    if group_ids:
        group_contact_ids = get_contacts_by_group_ids(group_ids)
        targets = [get_contact(cid) for cid in group_contact_ids]
        targets = [c for c in targets if c]
    elif contact_ids:
        targets = [get_contact(cid) for cid in contact_ids]
        targets = [c for c in targets if c]
    else:
        targets = list_contacts(stage=filter_stage, tag=filter_tag)

    if not targets:
        raise HTTPException(400, "No contacts match the selected filters")

    # Pre-create the campaign record with status "sending"
    campaign = create_campaign(
        name=campaign_name,
        template_id=template_id,
        template_name=template.get("name", ""),
        target_count=len(targets),
        sent=0,
        failed=0,
        delivered=0,
        read=0,
        replied=0,
        filter_stage=filter_stage,
        filter_tag=filter_tag,
        contact_ids=contact_ids,
        scheduled_at=scheduled_at,
        reply_mode=reply_mode,
        campaign_kb=campaign_kb_text,
    )
    campaign_id = campaign["id"]

    # Update campaign status to "sending"
    update_campaign(campaign_id, status="sending")

    # Save campaign-specific knowledge base if provided
    if campaign_kb_text:
        save_campaign_kb(campaign_id, campaign_kb_text)

    # Associate target contacts with this campaign (for reply routing)
    target_ids = [c["contact_id"] for c in targets]
    associate_contacts_to_campaign(target_ids, campaign_id)

    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"

    # --- Background worker function ---
    async def _campaign_send_worker(job_id: str, params: dict, update_progress):
        """Async worker that sends campaign messages in the background."""
        p_template = params["template"]
        p_targets = params["targets"]
        p_workspace_id = params["workspace_id"]
        p_campaign_id = params["campaign_id"]
        p_campaign_name = params["campaign_name"]
        p_actor_id = params["actor_id"]

        sent = 0
        failed = 0
        delivered = 0
        not_on_wa = 0
        total_targets = len(p_targets)

        for idx, contact in enumerate(p_targets):
            phone = contact.get("phone", "")
            if not phone:
                failed += 1
                update_progress(job_id, idx + 1, total_targets, failed)
                continue

            # Skip opted-out contacts
            phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
            if not can_message(phone_e164):
                failed += 1
                update_progress(job_id, idx + 1, total_targets, failed)
                continue

            try:
                rendered_msg = render_template(p_template, contact)
                if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
                    # Always send via template API for campaigns.
                    # Campaigns initiate conversations outside the 24h window,
                    # so free-form text will be rejected by Meta.
                    components = _build_template_components(p_template, contact)
                    result = await send_template_message(
                        phone,
                        p_template.get("name", ""),
                        p_template.get("language", "en"),
                        components=components or None,
                    )
                    # Check for Meta API errors
                    if "error" in result:
                        error_code = result["error"].get("code", 0)
                        error_msg = result["error"].get("message", "Unknown error")
                        # 132000 = template not found on Meta
                        # 132001 = template not approved
                        # 131047 = re-engagement message outside 24h without template
                        # 470    = contact not on WhatsApp
                        if error_code in (132000, 132001):
                            failed += 1
                            logger.error(
                                "Campaign %s: Template '%s' not registered/approved on Meta (code=%s). "
                                "Submit the template to Meta for approval first.",
                                p_campaign_id, p_template.get("name"), error_code,
                            )
                            # Fatal template error — abort remaining sends
                            failed += (total_targets - idx - 1)
                            update_campaign(p_campaign_id, sent=sent, failed=failed,
                                            delivered=delivered, status="failed",
                                            not_on_whatsapp=not_on_wa)
                            logger.error(
                                "Campaign %s ABORTED: template not approved on Meta", p_campaign_id
                            )
                            update_progress(job_id, idx + 1, total_targets, failed)
                            return  # Stop the entire campaign
                        elif error_code == 470:
                            # Contact not on WhatsApp
                            not_on_wa += 1
                            failed += 1
                            logger.info(
                                "Campaign %s: %s not on WhatsApp (code=470)",
                                p_campaign_id, phone,
                            )
                            update_progress(job_id, idx + 1, total_targets, failed)
                            continue
                        else:
                            failed += 1
                            logger.warning(
                                "Campaign %s send failed for %s: [%s] %s",
                                p_campaign_id, phone, error_code, error_msg,
                            )
                            update_progress(job_id, idx + 1, total_targets, failed)
                            continue
                else:
                    # Dev/test mode: no WhatsApp configured — save locally only
                    logger.debug("Campaign %s: No WA configured, saving locally for %s", p_campaign_id, phone)
                save_message(contact["contact_id"], "outbound", rendered_msg, sent_by="campaign")
                sent += 1
                delivered += 1
            except DailyLimitExceeded as e:
                # Stop entire campaign if daily limit hit
                failed += (total_targets - idx)
                logger.error("Campaign %s halted: daily rate limit exceeded at %d/%d", p_campaign_id, idx, total_targets)
                break
            except Exception as e:
                failed += 1
                logger.warning(f"Campaign {p_campaign_id} send failed for {phone}: {e}")

            update_progress(job_id, idx + 1, total_targets, failed)

            # Push live progress via WebSocket every 5 sends or at start/end
            if (idx % 5 == 0) or (idx == total_targets - 1):
                await ws_manager.send_to_workspace(p_workspace_id, {
                    "type": "campaign_progress",
                    "campaign_id": p_campaign_id,
                    "job_id": job_id,
                    "sent": sent,
                    "total": total_targets,
                    "failed": failed,
                    "pct": round((idx + 1) / max(total_targets, 1) * 100, 1),
                    "status": "sending" if idx < total_targets - 1 else "completed",
                })

            await asyncio.sleep(0.1)  # Rate limit between sends

        # Increment template usage
        increment_template_usage(template_id)

        # Update campaign record with final stats
        update_campaign(p_campaign_id, sent=sent, failed=failed, delivered=delivered,
                        not_on_whatsapp=not_on_wa, status="completed")

        # Audit + webhook
        log_audit("campaign.sent", "campaign", p_campaign_id, actor_id=p_actor_id,
                  details={"sent": sent, "failed": failed, "total": total_targets})
        await webhook_dispatcher_mod.dispatch("campaign.completed", {
            "campaign_id": p_campaign_id,
            "name": p_campaign_name,
            "sent": sent,
            "failed": failed,
            "total": total_targets,
        })

        # Final WebSocket notification
        await ws_manager.send_to_workspace(p_workspace_id, {
            "type": "campaign_completed",
            "campaign_id": p_campaign_id,
            "sent": sent,
            "failed": failed,
            "total": total_targets,
        })

    # Enqueue background job
    job_id = await job_queue.enqueue(
        "campaign_send",
        {
            "template": template,
            "targets": targets,
            "workspace_id": workspace_id,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "actor_id": actor_id,
        },
        _campaign_send_worker,
    )

    # Meter campaign usage
    increment_usage(workspace_id, "campaigns")

    campaign["job_id"] = job_id
    campaign["status"] = "sending"
    return {"campaign": campaign, "job_id": job_id}


@app.post("/api/campaigns/{campaign_id}/retarget")
async def api_retarget_campaign(campaign_id: str, request: Request):
    """Retarget failed/unread contacts from a previous campaign via background job."""
    ctx = _check_api_key(request)
    _check_subscription_active(ctx)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    retarget_type = body.get("type", "failed")  # "failed" or "unread"

    original = get_campaign(campaign_id)
    if not original:
        raise HTTPException(404, "Campaign not found")

    template = get_template(original.get("template_id", ""))
    if not template:
        raise HTTPException(404, "Original template no longer exists")

    # For retargeting, re-send to original contacts
    contact_ids = original.get("contact_ids", [])
    if contact_ids:
        targets = [get_contact(cid) for cid in contact_ids]
        targets = [c for c in targets if c]
    else:
        targets = list_contacts(
            stage=original.get("filter_stage") or None,
            tag=original.get("filter_tag") or None,
        )

    if not targets:
        raise HTTPException(400, "No contacts to retarget")

    # Pre-create retarget campaign record
    new_campaign = create_campaign(
        name=f"{original['name']} (Retarget)",
        template_id=original.get("template_id", ""),
        template_name=original.get("template_name", ""),
        target_count=len(targets),
        sent=0,
        failed=0,
        delivered=0,
        filter_stage=original.get("filter_stage"),
        filter_tag=original.get("filter_tag"),
        contact_ids=contact_ids,
    )
    retarget_id = new_campaign["id"]
    update_campaign(retarget_id, status="sending")

    # Background worker for retarget
    async def _retarget_worker(job_id: str, params: dict, update_progress):
        p_template = params["template"]
        p_targets = params["targets"]
        p_campaign_id = params["campaign_id"]
        p_workspace_id = params["workspace_id"]

        sent = 0
        failed = 0
        not_on_wa = 0
        total = len(p_targets)

        for idx, contact in enumerate(p_targets):
            phone = contact.get("phone", "")
            if not phone:
                failed += 1
                update_progress(job_id, idx + 1, total, failed)
                continue

            phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
            if not can_message(phone_e164):
                failed += 1
                update_progress(job_id, idx + 1, total, failed)
                continue

            try:
                rendered_msg = render_template(p_template, contact)
                if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
                    components = _build_template_components(p_template, contact)
                    result = await send_template_message(
                        phone,
                        p_template.get("name", ""),
                        p_template.get("language", "en"),
                        components=components or None,
                    )
                    if "error" in result:
                        error_code = result["error"].get("code", 0)
                        if error_code == 470:
                            not_on_wa += 1
                        if error_code in (132000, 132001):
                            # Fatal: template not registered on Meta
                            failed += (total - idx)
                            update_campaign(p_campaign_id, sent=sent, failed=failed,
                                            delivered=sent, not_on_whatsapp=not_on_wa,
                                            status="failed")
                            return
                        failed += 1
                        update_progress(job_id, idx + 1, total, failed)
                        continue
                save_message(contact["contact_id"], "outbound", rendered_msg, sent_by="campaign-retarget")
                sent += 1
            except DailyLimitExceeded:
                failed += (total - idx)
                break
            except Exception as exc:
                failed += 1
                logger.warning("Retarget %s send failed for %s: %s", p_campaign_id, phone, exc)

            update_progress(job_id, idx + 1, total, failed)

            if (idx % 5 == 0) or (idx == total - 1):
                await ws_manager.send_to_workspace(p_workspace_id, {
                    "type": "campaign_progress",
                    "campaign_id": p_campaign_id,
                    "job_id": job_id,
                    "sent": sent,
                    "total": total,
                    "failed": failed,
                    "pct": round((idx + 1) / max(total, 1) * 100, 1),
                    "status": "sending" if idx < total - 1 else "completed",
                })

            await asyncio.sleep(0.1)

        update_campaign(p_campaign_id, sent=sent, failed=failed, delivered=sent,
                        not_on_whatsapp=not_on_wa, status="completed")
        await ws_manager.send_to_workspace(p_workspace_id, {
            "type": "campaign_completed",
            "campaign_id": p_campaign_id,
            "sent": sent,
            "failed": failed,
            "not_on_whatsapp": not_on_wa,
            "total": total,
        })

    job_id = await job_queue.enqueue(
        "campaign_retarget",
        {
            "template": template,
            "targets": targets,
            "campaign_id": retarget_id,
            "workspace_id": workspace_id,
        },
        _retarget_worker,
    )

    new_campaign["job_id"] = job_id
    new_campaign["status"] = "sending"
    return {"campaign": new_campaign, "job_id": job_id}


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
#  ANALYTICS API
# ====================================================================

@app.get("/api/analytics")
async def api_analytics(request: Request):
    """Full analytics snapshot for the dashboard analytics page."""
    _check_api_key(request)
    contacts = list_contacts()
    return get_analytics_snapshot(contacts)


@app.get("/api/analytics/conversations")
async def api_analytics_conversations(request: Request, days: int = 7):
    _check_api_key(request)
    return get_conversation_stats(days=days)


@app.get("/api/analytics/pipeline")
async def api_analytics_pipeline(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    return get_pipeline_analytics(contacts)


@app.get("/api/analytics/campaigns")
async def api_analytics_campaigns(request: Request, days: int = 30):
    _check_api_key(request)
    result = get_campaign_analytics(days=days)

    # Enrich with WhatsApp conversation cost estimates
    # Meta charges per conversation (not per message):
    # Marketing: ~₹0.76/conversation, Utility: ~₹0.34, Service: free (24h window)
    from outbound import get_campaign_stats as _get_cmp_stats
    stats = _get_cmp_stats()
    total_delivered = stats.get("total_delivered", 0)
    estimated_wa_cost_inr = round(total_delivered * 0.76, 2)  # Marketing rate
    result["whatsapp_cost_estimate"] = {
        "total_conversations": total_delivered,
        "estimated_cost_inr": estimated_wa_cost_inr,
        "rate_per_conversation_inr": 0.76,
        "category": "marketing",
        "note": "Estimate based on Meta marketing conversation rate. Actual costs may vary.",
    }
    return result


@app.get("/api/analytics/ai")
async def api_analytics_ai(request: Request, days: int = 7):
    _check_api_key(request)
    return get_ai_performance(days=days)


@app.get("/api/analytics/leads")
async def api_analytics_leads(request: Request):
    _check_api_key(request)
    contacts = list_contacts()
    return get_lead_quality_report(contacts)


@app.get("/api/analytics/trend")
async def api_analytics_trend(request: Request, days: int = 14):
    _check_api_key(request)
    return get_trend(days=days)


# ====================================================================
#  AUTH API — Login / Session
# ====================================================================

@app.post("/api/auth/login")
async def api_login(request: Request):
    """Authenticate user and return a session token."""
    try:
        body_raw = await request.json()
        body = LoginRequest(**body_raw)
    except Exception as e:
        raise HTTPException(400, str(e))
    email = body.email
    password = body.password
    workspace_id = body.workspace_id

    token = login(email, password, workspace_id)
    if not token:
        raise HTTPException(401, "Invalid email or password")

    from auth_manager import get_user_by_email
    user = get_user_by_email(email, workspace_id)

    # Check if password change is required (default credentials)
    password_change_required = False
    if user:
        from auth_manager import _load as _auth_load
        all_users = _auth_load("users.json")
        raw_user = all_users.get(user.get("user_id", ""), {})
        password_change_required = raw_user.get("password_change_required", False)

    return {
        "token": token,
        "user": user,
        "password_change_required": password_change_required,
    }



@app.post("/api/auth/logout")
async def api_logout(request: Request):
    """Logout — revokes the session token server-side."""
    from auth_manager import revoke_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token:
            revoke_token(token)
    return {"ok": True}


@app.get("/api/auth/me")
async def api_me(request: Request):
    """Get current user info from session token."""
    ctx = _check_api_key(request)
    return {
        "user": ctx.get("user"),
        "workspace": ctx.get("workspace"),
    }


# ====================================================================
#  WORKSPACE & USER MANAGEMENT API
# ====================================================================

@app.get("/api/workspace")
async def api_get_workspace(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    ws = get_workspace(workspace_id)
    if not ws:
        # Return stub for default workspace
        return {"workspace": {"workspace_id": "default", "name": "My Business", "plan": "starter"}}
    # Don't expose the raw api_key in responses
    safe_ws = {k: v for k, v in ws.items() if k != "api_key"}
    return {"workspace": safe_ws}


@app.patch("/api/workspace")
async def api_update_workspace(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    if workspace_id == "default":
        return {"workspace": {"workspace_id": "default"}}
    try:
        ws = update_workspace(workspace_id, **body)
        safe_ws = {k: v for k, v in ws.items() if k != "api_key"}
        return {"workspace": safe_ws}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/users")
async def api_list_users(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    users = list_workspace_users(workspace_id)
    return {"users": users}


@app.post("/api/users")
async def api_create_user(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    try:
        user = create_user(
            email=body.get("email", ""),
            password=body.get("password", ""),
            workspace_id=workspace_id,
            role=body.get("role", "agent"),
            name=body.get("name", ""),
        )
        return {"user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/users/{user_id}")
async def api_update_user(user_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    try:
        user = update_user(user_id, **body)
        return {"user": user}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/users/{user_id}")
async def api_delete_user(user_id: str, request: Request):
    _check_api_key(request)
    delete_user(user_id)
    return {"ok": True}


@app.post("/api/users/{user_id}/change-password")
async def api_change_password(user_id: str, request: Request):
    _check_api_key(request)
    body = await request.json()
    ok = change_password(user_id, body.get("old_password", ""), body.get("new_password", ""))
    if not ok:
        raise HTTPException(400, "Old password is incorrect")
    return {"ok": True}


# ====================================================================
#  INVITATIONS API
# ====================================================================

@app.get("/api/invites")
async def api_list_invites(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    invites = get_workspace_invites(workspace_id)
    return {"invites": invites}


@app.post("/api/invites")
async def api_create_invite(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    invited_by = ctx.get("user", {}).get("user_id", "unknown") if ctx.get("user") else "admin"
    try:
        invite = create_invite(
            workspace_id=workspace_id,
            email=body.get("email", ""),
            role=body.get("role", "agent"),
            invited_by=invited_by,
        )
        return {"invite": invite}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/invites/{token}/accept")
async def api_accept_invite(token: str, request: Request):
    body = await request.json()
    user = accept_invite(token, body.get("name", ""), body.get("password", ""))
    if not user:
        raise HTTPException(400, "Invalid or expired invitation")
    return {"user": user}


# ====================================================================
#  BILLING API
# ====================================================================

@app.get("/api/billing/plans")
async def api_billing_plans(request: Request):
    """Get all available plans for display."""
    _check_api_key(request)
    return {"plans": get_plans_for_display()}


@app.get("/api/billing/subscription")
async def api_get_subscription(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    sub = get_subscription(workspace_id)
    if not sub:
        # Auto-create starter trial for new workspaces
        sub = create_subscription(workspace_id, "starter", trial=True)
    return {"subscription": sub}


@app.get("/api/billing/usage")
async def api_billing_usage(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    summary = get_usage_summary(workspace_id)
    return summary


@app.post("/api/billing/upgrade")
async def api_billing_upgrade(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    plan_id = body.get("plan_id", "")
    if plan_id not in PLANS:
        raise HTTPException(400, f"Invalid plan '{plan_id}'")
    try:
        # Ensure subscription exists before upgrading
        if not get_subscription(workspace_id):
            create_subscription(workspace_id, plan_id, trial=False)
        sub = upgrade_plan(workspace_id, plan_id)
        return {"subscription": sub, "ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/billing/cancel")
async def api_billing_cancel(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    at_period_end = body.get("at_period_end", True)
    sub = cancel_subscription(workspace_id, at_period_end=at_period_end)
    return {"subscription": sub, "ok": True}


@app.post("/api/billing/webhook/stripe")
async def api_stripe_webhook(request: Request):
    """Stripe webhook endpoint. Verify signature in production."""
    body = await request.json()
    event_type = body.get("type", "")
    data_obj = body.get("data", {}).get("object", {})
    result = handle_stripe_webhook(event_type, data_obj)
    return result


# ====================================================================
#  RAZORPAY PAYMENT API
# ====================================================================

@app.get("/api/payments/config")
async def api_payment_config(request: Request):
    """Return payment gateway configuration for the frontend."""
    _check_api_key(request)
    import payment_gateway as pg
    return {
        "provider": "razorpay" if pg.is_configured() else "none",
        "key_id": pg.RAZORPAY_KEY_ID if pg.is_configured() else "",
        "configured": pg.is_configured(),
    }


@app.post("/api/payments/subscribe")
async def api_create_payment_subscription(request: Request):
    """
    Create a Razorpay subscription for the current workspace.

    Body:
      - plan_id: "starter" | "growth" | "pro"

    Returns:
      - subscription_id, short_url (redirect user to this)
    """
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()
    plan_id = body.get("plan_id", "")

    if plan_id not in ("starter", "growth", "pro"):
        raise HTTPException(400, f"Invalid plan_id '{plan_id}'")

    import payment_gateway as pg
    if not pg.is_configured():
        raise HTTPException(503, "Payment gateway not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")

    # Get user email from auth context
    user = ctx.get("user") or {}
    email = user.get("email", "")
    name = user.get("name", "")

    try:
        result = pg.create_subscription(
            workspace_id=workspace_id,
            plan_id=plan_id,
            customer_email=email,
            customer_name=name,
        )
        return result
    except Exception as e:
        logger.error(f"Razorpay subscription creation failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/payments/verify")
async def api_verify_payment(request: Request):
    """
    Verify a Razorpay payment signature after checkout.

    Body:
      - razorpay_payment_id
      - razorpay_signature
      - razorpay_subscription_id (for subscriptions)
      - razorpay_order_id (for one-time payments)
    """
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    body = await request.json()

    import payment_gateway as pg

    verified = pg.verify_payment_signature(
        razorpay_order_id=body.get("razorpay_order_id", ""),
        razorpay_payment_id=body.get("razorpay_payment_id", ""),
        razorpay_signature=body.get("razorpay_signature", ""),
        razorpay_subscription_id=body.get("razorpay_subscription_id", ""),
    )

    if verified:
        # Update billing state
        plan_id = body.get("plan_id", "")
        if plan_id:
            try:
                upgrade_plan(workspace_id, plan_id)
                update_subscription(
                    workspace_id,
                    status="active",
                    payment_provider="razorpay",
                    payment_subscription_id=body.get("razorpay_subscription_id", ""),
                )
            except Exception as e:
                logger.error(f"Post-payment plan update failed: {e}")

        return {"verified": True, "ok": True}
    else:
        raise HTTPException(400, "Payment signature verification failed")


@app.post("/api/payments/webhook/razorpay")
async def api_razorpay_webhook(request: Request):
    """
    Razorpay webhook endpoint.
    Verifies signature and processes subscription/payment events.
    """
    import payment_gateway as pg

    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not pg.verify_webhook_signature(body_bytes, signature):
        logger.warning("Razorpay webhook: invalid signature")
        raise HTTPException(400, "Invalid webhook signature")

    try:
        body = json.loads(body_bytes)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    event_type = body.get("event", "")
    payload = body.get("payload", {}).get("subscription", body.get("payload", {}))
    # Flatten: payload.subscription.entity → payload.entity
    if "entity" not in payload:
        # Try payment payload
        payload = body.get("payload", {}).get("payment", body.get("payload", {}))

    result = pg.process_webhook_event(event_type, payload)
    return result


@app.get("/api/payments/invoice/{workspace_id}")
async def api_get_invoice(workspace_id: str, request: Request):
    """Get GST invoice data for a workspace's current plan."""
    ctx = _check_api_key(request)
    # Only allow workspace members to view their own invoices
    if ctx.get("workspace_id", "default") != workspace_id:
        raise HTTPException(403, "Cannot view invoices for another workspace")

    import payment_gateway as pg
    sub = get_subscription(workspace_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    invoice = pg.get_invoice_data(workspace_id, plan_id)
    return {"invoice": invoice}


# ====================================================================
#  ONBOARDING API
# ====================================================================

@app.get("/api/onboarding")
async def api_onboarding(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    state = auto_detect_progress(workspace_id)
    return state


@app.post("/api/onboarding/step/{step_id}/done")
async def api_onboarding_step_done(step_id: str, request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    try:
        state = mark_step_done(workspace_id, step_id)
        return state
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/onboarding/step/{step_id}/skip")
async def api_onboarding_step_skip(step_id: str, request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    try:
        state = skip_step(workspace_id, step_id)
        return state
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/onboarding/readiness")
async def api_onboarding_readiness(request: Request):
    ctx = _check_api_key(request)
    workspace_id = ctx.get("workspace_id", "default")
    return get_readiness_checklist(workspace_id)


# ====================================================================
#  WEBSOCKET — Real-time push events
# ====================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None, key: str = None):
    """
    WebSocket endpoint for real-time dashboard updates.

    Authentication:
      ?token=<jwt>      — session token from /api/auth/login
      ?key=<api_key>    — API key (dev / server-to-server)

    Events pushed (JSON):
      {"type": "new_message",       "contact_id": ..., "direction": ..., "content": ...}
      {"type": "handoff_triggered", "contact_id": ..., "reason": ...}
      {"type": "bot_resumed",       "contact_id": ...}
      {"type": "draft_ready",       "contact_id": ..., "draft_preview": ...}
      {"type": "contact_updated",   "contact_id": ..., "fields": {...}}
      {"type": "campaign_progress", "campaign_id": ..., "sent": ..., "total": ...}
      {"type": "ping"}              — keepalive every 30s
    """
    workspace_id = "default"
    authenticated = False

    # Validate auth
    if token:
        ctx = validate_token(token)
        if ctx:
            workspace_id = ctx.get("workspace_id", "default")
            authenticated = True
    elif key:
        ws = validate_api_key(key)
        if ws:
            workspace_id = ws.get("workspace_id", "default")
            authenticated = True

    if not authenticated:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await ws_manager.connect(websocket, workspace_id)

    # Start keepalive ping task
    async def _keepalive():
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_text('{"type":"ping"}')
            except Exception:
                break

    ping_task = asyncio.create_task(_keepalive())

    try:
        # Send connection confirmation
        await websocket.send_text('{"type":"connected","status":"ok"}')
        # Keep connection alive — process any inbound messages (ack only)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                # No message in 60s — send server-side ping
                try:
                    await websocket.send_text('{"type":"ping"}')
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        ping_task.cancel()
        ws_manager.disconnect(websocket)


# ====================================================================
#  OPT-OUT MANAGEMENT API
# ====================================================================

@app.get("/api/optouts")
async def api_list_optouts(request: Request):
    """List all opted-out contacts."""
    _check_api_key(request)
    from optout_manager import list_optouts, get_optout_count
    optouts = list_optouts()
    return {"optouts": optouts, "count": get_optout_count()}


@app.post("/api/optouts/{phone}/optin")
async def api_manual_optin(phone: str, request: Request):
    """Manually re-subscribe a contact."""
    _check_api_key(request)
    record = record_optin(phone)
    return {"ok": True, "record": record}


@app.post("/api/optouts/{phone}/optout")
async def api_manual_optout(phone: str, request: Request):
    """Manually opt-out a contact."""
    _check_api_key(request)
    record = record_optout(phone, reason="Manual opt-out from dashboard")
    return {"ok": True, "record": record}


# ====================================================================
#  BACKGROUND JOB STATUS API
# ====================================================================

@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str, request: Request):
    """Get status and progress of a background job."""
    _check_api_key(request)
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs")
async def api_list_jobs(request: Request, job_type: str = None, status: str = None):
    """List background jobs."""
    _check_api_key(request)
    jobs = job_queue.list_jobs(job_type=job_type, status=status)
    return {"jobs": jobs, "count": len(jobs)}


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str, request: Request):
    """Cancel a running background job."""
    _check_api_key(request)
    cancelled = job_queue.cancel(job_id)
    if not cancelled:
        raise HTTPException(400, "Job cannot be cancelled (not running or already done)")
    return {"ok": True, "job_id": job_id}


# ====================================================================
#  ASSIGNMENT API
# ====================================================================

@app.get("/api/assignments")
async def api_list_assignments(request: Request):
    """List all conversation assignments."""
    _check_api_key(request)
    return {"assignments": get_all_assignments()}


@app.get("/api/assignments/queue")
async def api_unassigned_queue(request: Request):
    """List unassigned conversations waiting for an agent."""
    _check_api_key(request)
    queue = get_unassigned_queue()
    return {"queue": queue, "count": len(queue)}


@app.get("/api/assignments/workload")
async def api_agent_workload(request: Request):
    """Get active conversation count per agent."""
    _check_api_key(request)
    return {"workload": get_agent_workload()}


@app.get("/api/assignments/{contact_id}")
async def api_get_assignment(contact_id: str, request: Request):
    """Get assignment for a specific contact."""
    _check_api_key(request)
    record = get_assignment(contact_id)
    if not record:
        raise HTTPException(404, "No assignment found for this contact")
    return {"assignment": record}


@app.post("/api/assignments/{contact_id}/assign")
async def api_assign_conversation(contact_id: str, request: Request):
    """Manually assign a conversation to an agent."""
    ctx = _check_api_key(request)
    body = await request.json()
    agent_id = body.get("agent_id", "")
    if not agent_id:
        raise HTTPException(400, "agent_id is required")
    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
    record = manual_assign(contact_id, agent_id, assigned_by=actor_id)
    log_audit("conversation.assigned", "contact", contact_id, actor_id=actor_id,
              details={"agent_id": agent_id})
    return {"assignment": record}


@app.post("/api/assignments/{contact_id}/claim")
async def api_claim_conversation(contact_id: str, request: Request):
    """Agent claims an unassigned conversation."""
    ctx = _check_api_key(request)
    agent_id = ctx.get("user", {}).get("user_id", "")
    if not agent_id:
        raise HTTPException(400, "Must be authenticated as a user to claim conversations")
    record = claim_conversation(contact_id, agent_id)
    return {"assignment": record}


@app.post("/api/assignments/{contact_id}/transfer")
async def api_transfer_conversation(contact_id: str, request: Request):
    """Transfer a conversation to another agent."""
    ctx = _check_api_key(request)
    body = await request.json()
    to_agent = body.get("to_agent_id", "")
    reason = body.get("reason", "")
    if not to_agent:
        raise HTTPException(400, "to_agent_id is required")
    from_agent = ctx.get("user", {}).get("user_id", "system") if ctx.get("user") else "system"
    record = transfer_conversation(contact_id, from_agent, to_agent, reason=reason)
    log_audit("conversation.transferred", "contact", contact_id, actor_id=from_agent,
              details={"to_agent": to_agent, "reason": reason})
    return {"assignment": record}


# ====================================================================
#  AUDIT LOG API
# ====================================================================

@app.get("/api/audit")
async def api_audit_log(
    request: Request,
    days: int = 7,
    action: str = None,
    resource_type: str = None,
    actor_id: str = None,
    limit: int = 200,
):
    """Get audit log entries."""
    _check_api_key(request)
    entries = get_audit_log(
        days=days,
        action=action,
        resource_type=resource_type,
        actor_id=actor_id,
        limit=limit,
    )
    return {"entries": entries, "count": len(entries)}


@app.get("/api/audit/stats")
async def api_audit_stats(request: Request, days: int = 30):
    """Get aggregate audit log statistics."""
    _check_api_key(request)
    return get_audit_stats(days=days)


# ====================================================================
#  SEGMENTATION API
# ====================================================================

@app.post("/api/segments/preview")
async def api_segment_preview(request: Request):
    """Preview contacts matching a segment definition."""
    _check_api_key(request)
    body = await request.json()
    segment = body.get("segment", {})
    sample_size = int(body.get("sample_size", 5))
    contacts = list_contacts()
    result = preview_segment(contacts, segment, sample_size=sample_size)
    return result


@app.get("/api/segments")
async def api_list_segments(request: Request):
    """List saved audience segments."""
    _check_api_key(request)
    return {"segments": list_segments()}


@app.post("/api/segments")
async def api_save_segment(request: Request):
    """Save a named audience segment for reuse."""
    _check_api_key(request)
    body = await request.json()
    name = body.get("name", "")
    segment = body.get("segment", {})
    if not name:
        raise HTTPException(400, "name is required")
    if not segment.get("conditions"):
        raise HTTPException(400, "segment.conditions is required")
    record = save_segment(name, segment)
    return {"segment": record}


@app.get("/api/segments/{segment_id}")
async def api_get_segment(segment_id: str, request: Request):
    """Get a saved segment."""
    _check_api_key(request)
    record = get_segment(segment_id)
    if not record:
        raise HTTPException(404, "Segment not found")
    return {"segment": record}


@app.delete("/api/segments/{segment_id}")
async def api_delete_segment(segment_id: str, request: Request):
    """Delete a saved segment."""
    _check_api_key(request)
    deleted = delete_segment(segment_id)
    if not deleted:
        raise HTTPException(404, "Segment not found")
    return {"ok": True}


@app.get("/api/segments/fields")
async def api_segment_fields(request: Request):
    """List all segmentable fields and supported operators."""
    _check_api_key(request)
    return {
        "fields": SEGMENTABLE_FIELDS,
        "operators": list(OPERATORS.keys()),
    }


# ====================================================================
#  CONTACT GROUPS API
# ====================================================================

@app.get("/api/groups")
async def api_list_groups(request: Request):
    """List all contact groups."""
    _check_api_key(request)
    groups = list_groups()
    return {"groups": groups, "count": len(groups), "colors": GROUP_COLORS}


@app.post("/api/groups")
async def api_create_group(request: Request):
    """Create a new contact group."""
    ctx = _check_api_key(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    group = create_group(
        name=name,
        description=body.get("description", ""),
        color=body.get("color", "#6366f1"),
    )
    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
    log_audit("group.created", "group", group["id"], actor_id=actor_id, details={"name": name})
    return {"group": group}


@app.get("/api/groups/{group_id}")
async def api_get_group(group_id: str, request: Request):
    """Get a group with its members."""
    _check_api_key(request)
    group = get_group(group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    members = get_group_members(group_id)
    return {"group": group, "members": members}


@app.patch("/api/groups/{group_id}")
async def api_update_group(group_id: str, request: Request):
    """Update a group (name, description, color)."""
    _check_api_key(request)
    body = await request.json()
    try:
        group = update_group(group_id, **body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"group": group}


@app.delete("/api/groups/{group_id}")
async def api_delete_group(group_id: str, request: Request):
    """Delete a group."""
    _check_api_key(request)
    deleted = delete_group(group_id)
    if not deleted:
        raise HTTPException(404, "Group not found")
    return {"ok": True}


@app.post("/api/groups/{group_id}/members")
async def api_add_group_members(group_id: str, request: Request):
    """Add contacts to a group."""
    _check_api_key(request)
    body = await request.json()
    contact_ids = body.get("contact_ids", [])
    if not contact_ids:
        raise HTTPException(400, "contact_ids is required")
    added = add_members(group_id, contact_ids)
    return {"added": added, "group_id": group_id}


@app.delete("/api/groups/{group_id}/members")
async def api_remove_group_members(group_id: str, request: Request):
    """Remove contacts from a group."""
    _check_api_key(request)
    body = await request.json()
    contact_ids = body.get("contact_ids", [])
    removed = remove_members(group_id, contact_ids)
    return {"removed": removed, "group_id": group_id}


@app.get("/api/contacts/{contact_id}/groups")
async def api_contact_groups(contact_id: str, request: Request):
    """Get all groups a contact belongs to."""
    _check_api_key(request)
    groups = get_contact_groups(contact_id)
    return {"groups": groups}


# ====================================================================
#  KNOWLEDGE BASE DOCUMENTS API (structured KB)
# ====================================================================

@app.get("/api/kb/documents")
async def api_list_kb_documents(request: Request, scope: str = "global", campaign_id: str = None, folder_id: str = None):
    """List all knowledge base documents, optionally filtered by folder."""
    _check_api_key(request)
    docs = kb_manager.list_documents(scope=scope, campaign_id=campaign_id, folder_id=folder_id)
    return {"documents": docs, "count": len(docs)}


@app.post("/api/kb/documents")
async def api_add_kb_document(request: Request):
    """Add a new document to the knowledge base."""
    _check_api_key(request)
    body = await request.json()
    title = body.get("title", "")
    content = body.get("content", "")
    scope = body.get("scope", "global")
    campaign_id = body.get("campaign_id")
    doc_type = body.get("type", "text")
    folder_id = body.get("folder_id") or None
    if not title:
        raise HTTPException(400, "title is required")
    if not content:
        raise HTTPException(400, "content is required")
    try:
        doc = kb_manager.add_document(title=title, content=content, doc_type=doc_type,
                                       scope=scope, campaign_id=campaign_id, folder_id=folder_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit("kb.updated", "kb", scope, details={"doc_id": doc["id"], "title": title})
    return {"document": doc}


@app.delete("/api/kb/documents/{doc_id}")
async def api_delete_kb_document(doc_id: str, request: Request):
    """Delete a knowledge base document."""
    _check_api_key(request)
    deleted = kb_manager.delete_document(doc_id)
    if not deleted:
        raise HTTPException(404, "Document not found")
    return {"ok": True}


@app.post("/api/kb/upload-file")
async def api_upload_kb_file(request: Request, file: UploadFile = File(...), title: str = Form(""), scope: str = Form("global"), campaign_id: str = Form(""), folder_id: str = Form("")):
    """Upload a single file to the knowledge base (backward-compatible)."""
    _check_api_key(request)
    result = await _process_kb_upload(file, title, scope, campaign_id, folder_id)
    return {"document": result["document"], "filename": result["filename"]}


@app.post("/api/kb/upload-files")
async def api_upload_kb_files(request: Request, files: List[UploadFile] = File(...), scope: str = Form("global"), campaign_id: str = Form(""), folder_id: str = Form("")):
    """Upload multiple files to the knowledge base in a single request."""
    _check_api_key(request)
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 20:
        raise HTTPException(400, "Too many files (max 20 per upload)")

    results = []
    errors = []
    for f in files:
        try:
            result = await _process_kb_upload(f, "", scope, campaign_id, folder_id)
            results.append(result)
        except HTTPException as e:
            errors.append({"filename": f.filename or "unknown", "error": e.detail})
        except Exception as e:
            errors.append({"filename": f.filename or "unknown", "error": str(e)})

    return {
        "uploaded": len(results),
        "failed": len(errors),
        "documents": [r["document"] for r in results],
        "errors": errors,
    }


async def _process_kb_upload(file: UploadFile, title: str, scope: str, campaign_id: str, folder_id: str = None) -> dict:
    """Shared logic for processing a single KB file upload."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("txt", "md", "pdf", "csv", "html", "htm"):
        raise HTTPException(400, f"Unsupported file type '.{ext}'. Allowed: .txt, .md, .pdf, .csv, .html, .htm")

    content_bytes = await file.read()
    if len(content_bytes) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(400, "File too large (max 5MB)")

    doc_title = title.strip() or file.filename

    if ext == "pdf":
        # Extract text from PDF
        try:
            import pdfplumber
            import io as _io
            text_parts = []
            with pdfplumber.open(_io.BytesIO(content_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            content = "\n\n".join(text_parts)
        except ImportError:
            raise HTTPException(500, "PDF support requires 'pdfplumber' package")
        except Exception as e:
            raise HTTPException(400, f"Failed to parse PDF: {e}")
        doc_type = "pdf"
    elif ext in ("html", "htm"):
        # Extract readable text from HTML
        try:
            from bs4 import BeautifulSoup
            raw_html = content_bytes.decode("utf-8", errors="replace")
            soup = BeautifulSoup(raw_html, "html.parser")
            # Remove script, style, and other non-content tags
            for tag in soup(["script", "style", "noscript", "iframe", "svg", "head"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
        except ImportError:
            raise HTTPException(500, "HTML support requires 'beautifulsoup4' package")
        except Exception as e:
            raise HTTPException(400, f"Failed to parse HTML: {e}")
        doc_type = "html"
    else:
        content = content_bytes.decode("utf-8", errors="replace")
        doc_type = {"txt": "text", "md": "markdown", "csv": "csv"}.get(ext, "text")

    if not content.strip():
        raise HTTPException(400, "File is empty or contains no extractable text")

    try:
        doc = kb_manager.add_document(
            title=doc_title, content=content, doc_type=doc_type,
            scope=scope, campaign_id=campaign_id or None,
            folder_id=folder_id or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit("kb.file_uploaded", "kb", scope, details={
        "doc_id": doc["id"], "title": doc_title, "filename": file.filename, "type": doc_type,
    })
    return {"document": doc, "filename": file.filename}


@app.post("/api/kb/query")
async def api_query_kb(request: Request):
    """Test a KB query — returns relevant chunks for a given question."""
    _check_api_key(request)
    body = await request.json()
    question = body.get("question", "")
    scope = body.get("scope", "global")
    campaign_id = body.get("campaign_id")
    n = int(body.get("n_results", 5))
    if not question:
        raise HTTPException(400, "question is required")
    result = kb_manager.query(question, scope=scope, campaign_id=campaign_id, n_results=n)
    return {"result": result, "question": question}


# ── KB Folders ──────────────────────────────────────────────────────

@app.get("/api/kb/folders")
async def api_list_kb_folders(request: Request, parent_id: str = None):
    """List knowledge base folders, optionally filtered by parent."""
    _check_api_key(request)
    folders = kb_manager.list_folders(parent_id=parent_id)
    # Include document counts per folder
    counts = kb_manager.get_folder_doc_counts()
    for f in folders:
        f["doc_count"] = counts.get(f["id"], 0)
    return {"folders": folders}


@app.post("/api/kb/folders")
async def api_create_kb_folder(request: Request):
    """Create a new knowledge base folder."""
    _check_api_key(request)
    body = await request.json()
    name = body.get("name", "").strip()
    parent_id = body.get("parent_id") or None
    if not name:
        raise HTTPException(400, "Folder name is required")
    if len(name) > 100:
        raise HTTPException(400, "Folder name too long (max 100 characters)")
    try:
        folder = kb_manager.create_folder(name=name, parent_id=parent_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit("kb.folder_created", "kb_folder", folder["id"], details={"name": name})
    return {"folder": folder}


@app.patch("/api/kb/folders/{folder_id}")
async def api_rename_kb_folder(folder_id: str, request: Request):
    """Rename a knowledge base folder."""
    _check_api_key(request)
    body = await request.json()
    new_name = body.get("name", "").strip()
    if not new_name:
        raise HTTPException(400, "Folder name is required")
    if len(new_name) > 100:
        raise HTTPException(400, "Folder name too long (max 100 characters)")
    folder = kb_manager.rename_folder(folder_id, new_name)
    if not folder:
        raise HTTPException(404, "Folder not found")
    log_audit("kb.folder_renamed", "kb_folder", folder_id, details={"name": new_name})
    return {"folder": folder}


@app.delete("/api/kb/folders/{folder_id}")
async def api_delete_kb_folder(folder_id: str, request: Request, recursive: bool = False):
    """Delete a knowledge base folder. If recursive=true, deletes all contents."""
    _check_api_key(request)
    deleted = kb_manager.delete_folder(folder_id, recursive=recursive)
    if not deleted:
        raise HTTPException(404, "Folder not found")
    log_audit("kb.folder_deleted", "kb_folder", folder_id, details={"recursive": recursive})
    return {"ok": True}


@app.patch("/api/kb/documents/{doc_id}/move")
async def api_move_kb_document(doc_id: str, request: Request):
    """Move a document to a different folder (or to root if folder_id is null)."""
    _check_api_key(request)
    body = await request.json()
    folder_id = body.get("folder_id")  # None means move to root
    try:
        doc = kb_manager.move_document(doc_id, folder_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not doc:
        raise HTTPException(404, "Document not found")
    log_audit("kb.document_moved", "kb", doc_id, details={"folder_id": folder_id})
    return {"document": doc}


# ====================================================================
#  OUTBOUND WEBHOOKS API
# ====================================================================

@app.get("/api/webhooks")
async def api_list_webhooks(request: Request):
    """List configured outbound webhook endpoints with supported event types."""
    _check_api_key(request)
    hooks = webhook_dispatcher_mod.list_webhooks()
    return {
        "webhooks": hooks,
        "count": len(hooks),
        "supported_events": webhook_dispatcher_mod.SUPPORTED_EVENTS,
    }


@app.post("/api/webhooks")
async def api_register_webhook(request: Request):
    """Register a new outbound webhook endpoint."""
    ctx = _check_api_key(request)
    body = await request.json()
    url = body.get("url", "")
    events = body.get("events", ["*"])
    secret = body.get("secret", "")
    name = body.get("name", "")
    if not url:
        raise HTTPException(400, "url is required")
    try:
        hook = webhook_dispatcher_mod.register_webhook(url=url, events=events, secret=secret, name=name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    actor_id = ctx.get("user", {}).get("user_id", "api") if ctx.get("user") else "api"
    log_audit("webhook.registered", "webhook", hook["id"], actor_id=actor_id,
              details={"url": url, "events": events})
    return {"webhook": hook}


@app.get("/api/webhooks/{webhook_id}")
async def api_get_webhook(webhook_id: str, request: Request):
    """Get a specific webhook configuration and delivery stats."""
    _check_api_key(request)
    wh = webhook_dispatcher_mod.get_webhook(webhook_id)
    if not wh:
        raise HTTPException(404, "Webhook not found")
    return {"webhook": wh}


@app.patch("/api/webhooks/{webhook_id}")
async def api_update_webhook(webhook_id: str, request: Request):
    """Update a webhook (url, events, active status, etc.)."""
    _check_api_key(request)
    body = await request.json()
    try:
        wh = webhook_dispatcher_mod.update_webhook(webhook_id, **body)
        return {"webhook": wh}
    except FileNotFoundError:
        raise HTTPException(404, "Webhook not found")


@app.delete("/api/webhooks/{webhook_id}")
async def api_delete_webhook(webhook_id: str, request: Request):
    """Delete an outbound webhook."""
    _check_api_key(request)
    deleted = webhook_dispatcher_mod.delete_webhook(webhook_id)
    if not deleted:
        raise HTTPException(404, "Webhook not found")
    log_audit("webhook.deleted", "webhook", webhook_id)
    return {"ok": True}


@app.post("/api/webhooks/{webhook_id}/test")
async def api_test_webhook(webhook_id: str, request: Request):
    """Send a test event to verify a webhook endpoint."""
    _check_api_key(request)
    result = await webhook_dispatcher_mod.dispatch_test(webhook_id)
    return result


# ====================================================================
#  RATE LIMITER STATUS API
# ====================================================================

@app.get("/api/whatsapp/profile")
async def api_get_whatsapp_profile(request: Request):
    """Fetch WhatsApp Business profile information."""
    _check_api_key(request)
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(503, "WhatsApp not configured")

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/whatsapp_business_profile"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    params = {"fields": "about,address,description,email,profile_picture_url,websites,vertical"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise HTTPException(resp.status, f"WhatsApp API error: {err}")
            data = await resp.json()
            profile_data = data.get("data", [{}])
            return {"profile": profile_data[0] if profile_data else {}}


@app.patch("/api/whatsapp/profile")
async def api_update_whatsapp_profile(request: Request):
    """Update WhatsApp Business profile (about, description, address, etc.)."""
    _check_api_key(request)
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(503, "WhatsApp not configured")

    body = await request.json()
    allowed_fields = {"about", "address", "description", "email", "websites", "vertical"}
    update_data = {k: v for k, v in body.items() if k in allowed_fields}

    if not update_data:
        raise HTTPException(400, f"No valid fields to update. Allowed: {allowed_fields}")

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/whatsapp_business_profile"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"messaging_product": "whatsapp", **update_data}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            result = await resp.json()
            if resp.status != 200:
                raise HTTPException(resp.status, f"WhatsApp API error: {result}")
            return {"ok": True, "result": result}


@app.post("/api/admin/backup")
async def api_backup_data(request: Request):
    """
    Create a backup of all critical data: SQLite DB, auth, billing, vector store.
    Returns a ZIP file containing everything needed to restore.
    """
    ctx = _check_api_key(request)

    import zipfile
    import io as _io
    import shutil

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. SQLite database
        db_path = DATA_DIR / "nazar.db"
        if db_path.exists():
            # Use SQLite backup (safe for WAL mode)
            import sqlite3
            backup_path = DATA_DIR / "nazar_backup.db"
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(backup_path))
            src.backup(dst)
            dst.close()
            src.close()
            zf.write(str(backup_path), "nazar.db")
            backup_path.unlink(missing_ok=True)

        # 2. Auth files
        auth_dir = DATA_DIR / "auth"
        if auth_dir.exists():
            for f in auth_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    zf.write(str(f), f"auth/{f.name}")

        # 3. Billing files
        billing_dir = DATA_DIR / "billing"
        if billing_dir.exists():
            for f in billing_dir.iterdir():
                if f.is_file():
                    zf.write(str(f), f"billing/{f.name}")

        # 4. Config
        config_path = DATA_DIR / "config.json"
        if config_path.exists():
            zf.write(str(config_path), "config.json")

        # 5. Templates
        templates_path = DATA_DIR / "templates.json"
        if templates_path.exists():
            zf.write(str(templates_path), "templates.json")

        # 6. Knowledge base
        kb_dir = DATA_DIR / "kb"
        if kb_dir.exists():
            for root, dirs, files in os.walk(str(kb_dir)):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, str(DATA_DIR))
                    zf.write(full, arcname)

        # 7. ChromaDB vector store (if small enough)
        chroma_dir = DATA_DIR / "contacts"
        if chroma_dir.exists():
            total_size = sum(f.stat().st_size for f in chroma_dir.rglob("*") if f.is_file())
            if total_size < 100 * 1024 * 1024:  # Only if under 100MB
                for root, dirs, files in os.walk(str(chroma_dir)):
                    for f in files:
                        full = os.path.join(root, f)
                        arcname = os.path.relpath(full, str(DATA_DIR))
                        zf.write(full, arcname)

    buf.seek(0)
    timestamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
    filename = f"nazar_backup_{timestamp}.zip"

    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Channels — Multi-phone-number management
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/channels")
async def api_list_channels(request: Request, include_inactive: bool = False):
    """List all channels (WhatsApp phone numbers) in the current workspace."""
    _check_api_key(request)
    channels = list_channels(include_inactive=include_inactive)
    # Redact access_token from list response
    for ch in channels:
        ch["access_token_set"] = bool(ch.get("access_token"))
        ch.pop("access_token", None)
    return {"channels": channels, "count": len(channels)}


@app.post("/api/channels")
async def api_create_channel(request: Request):
    """
    Register a new WhatsApp phone number as a channel.

    Body (CreateChannelRequest):
      - phone_number_id: str (required) — Meta phone number ID
      - access_token: str (required)
      - display_name: str — e.g., "Sales", "Support"
      - waba_id: str
      - persona_prompt: str — system prompt override
      - default_reply_mode: str — auto_ai | human_only | ai_draft
      - kb_scope: str — 'global' or custom scope
      - is_primary: bool
    """
    ctx = _check_api_key(request)
    check_permission(ctx, "admin")
    body = CreateChannelRequest(**(await request.json()))

    try:
        ch = create_channel_record(
            phone_number_id=body.phone_number_id,
            access_token=body.access_token,
            display_name=body.display_name,
            waba_id=body.waba_id,
            persona_prompt=body.persona_prompt,
            default_reply_mode=body.default_reply_mode,
            kb_scope=body.kb_scope,
            is_primary=body.is_primary,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))

    log_audit("channel.created", "channel", ch["id"], ctx.get("user_id", "system"),
              {"display_name": ch["display_name"], "phone_number_id": ch["phone_number_id"]})

    # Redact token from response
    ch["access_token_set"] = True
    ch.pop("access_token", None)
    return ch


@app.get("/api/channels/{channel_id}")
async def api_get_channel(channel_id: str, request: Request):
    """Get a single channel by ID."""
    _check_api_key(request)
    ch = get_channel_record(channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found")
    ch["access_token_set"] = bool(ch.get("access_token"))
    ch.pop("access_token", None)
    return ch


@app.put("/api/channels/{channel_id}")
async def api_update_channel(channel_id: str, request: Request):
    """
    Update a channel's configuration.

    Body (UpdateChannelRequest): any subset of mutable fields.
    """
    ctx = _check_api_key(request)
    check_permission(ctx, "admin")
    body = UpdateChannelRequest(**(await request.json()))
    updates = body.dict(exclude_none=True)

    # Convert bool is_primary/is_active to int for SQLite
    if "is_primary" in updates:
        updates["is_primary"] = 1 if updates["is_primary"] else 0
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0

    try:
        ch = update_channel_record(channel_id, updates)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not ch:
        raise HTTPException(404, "Channel not found")

    log_audit("channel.updated", "channel", channel_id, ctx.get("user_id", "system"),
              {"updates": list(updates.keys())})

    ch["access_token_set"] = bool(ch.get("access_token"))
    ch.pop("access_token", None)
    return ch


@app.delete("/api/channels/{channel_id}")
async def api_delete_channel(channel_id: str, request: Request, hard: bool = False):
    """
    Deactivate (soft-delete) a channel.
    Pass ?hard=true to permanently remove (admin only).
    """
    ctx = _check_api_key(request)
    check_permission(ctx, "admin")

    if channel_id == "default":
        raise HTTPException(400, "Cannot delete the default channel")

    deleted = delete_channel_record(channel_id, hard=hard)
    if not deleted:
        raise HTTPException(404, "Channel not found")

    log_audit("channel.deleted", "channel", channel_id, ctx.get("user_id", "system"),
              {"hard": hard})
    return {"ok": True, "hard": hard}


@app.post("/api/channels/{channel_id}/verify")
async def api_verify_channel(channel_id: str, request: Request):
    """
    Test connectivity for a channel by sending a lightweight API call to Meta.
    Returns success/failure + Meta response.
    """
    ctx = _check_api_key(request)
    creds = get_channel_credentials(channel_id)
    if not creds:
        raise HTTPException(404, "Channel not found or inactive")

    test_url = f"https://graph.facebook.com/v21.0/{creds['phone_number_id']}"
    headers = {"Authorization": f"Bearer {creds['access_token']}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status = resp.status
                data = await resp.json()
                return {
                    "ok": status == 200,
                    "status_code": status,
                    "phone_number_id": creds["phone_number_id"],
                    "meta_response": data,
                }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/channels/{channel_id}/stats")
async def api_channel_stats(channel_id: str, request: Request):
    """Get basic statistics for a channel (contact/message counts)."""
    _check_api_key(request)
    ch = get_channel_record(channel_id)
    if not ch:
        raise HTTPException(404, "Channel not found")

    from database import get_db
    with get_db() as conn:
        contact_count = conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE channel_id = ? AND workspace_id = ?",
            (channel_id, get_workspace()),
        ).fetchone()[0]
        message_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE channel_id = ? AND workspace_id = ?",
            (channel_id, get_workspace()),
        ).fetchone()[0]
        active_handoffs = conn.execute(
            "SELECT COUNT(*) FROM handoff_states WHERE channel_id = ? AND workspace_id = ? AND bot_active = 0",
            (channel_id, get_workspace()),
        ).fetchone()[0]

    return {
        "channel_id": channel_id,
        "display_name": ch["display_name"],
        "contacts": contact_count,
        "messages": message_count,
        "active_handoffs": active_handoffs,
    }


@app.get("/api/contacts/{phone}/unified")
async def api_unified_contact_view(phone: str, request: Request):
    """
    Cross-channel contact view: show all channel interactions for a phone number
    within the current workspace.
    """
    _check_api_key(request)
    ws = get_workspace()

    from database import get_db, rows_to_list as db_rows_to_list
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.*, ch.display_name AS channel_name,
                      (SELECT COUNT(*) FROM messages m WHERE m.contact_id = c.id) AS message_count
               FROM contacts c
               LEFT JOIN channels ch ON c.channel_id = ch.id
               WHERE c.workspace_id = ? AND c.phone = ?
               ORDER BY c.last_replied_at DESC""",
            (ws, phone),
        ).fetchall()

    if not rows:
        raise HTTPException(404, "No contacts found with this phone number")

    contacts = db_rows_to_list(rows)
    return {
        "phone": phone,
        "channels": contacts,
        "total_channels": len(contacts),
    }


@app.get("/api/whatsapp/numbers")
async def api_list_whatsapp_numbers(request: Request):
    """
    List configured WhatsApp phone numbers.

    Multi-number support: businesses can use different numbers
    for sales vs. support vs. marketing.
    """
    _check_api_key(request)
    numbers = []
    # Primary number (always present if configured)
    if WHATSAPP_PHONE_NUMBER_ID:
        numbers.append({
            "id": WHATSAPP_PHONE_NUMBER_ID,
            "label": "Primary",
            "is_primary": True,
            "access_token_set": bool(WHATSAPP_ACCESS_TOKEN),
        })
    # Check for additional numbers from config
    config = _load_config()
    additional_numbers = config.get("additional_wa_numbers", [])
    for num in additional_numbers:
        numbers.append({
            "id": num.get("phone_number_id", ""),
            "label": num.get("label", ""),
            "is_primary": False,
            "access_token_set": bool(num.get("access_token")),
        })
    return {"numbers": numbers, "multi_number_enabled": len(numbers) > 1}


@app.post("/api/whatsapp/numbers")
async def api_add_whatsapp_number(request: Request):
    """
    Add an additional WhatsApp phone number.

    Body:
      - phone_number_id: str — Meta phone number ID
      - access_token: str — access token for this number
      - label: str — e.g., "Sales", "Support"
    """
    ctx = _check_api_key(request)
    body = await request.json()
    phone_number_id = body.get("phone_number_id", "").strip()
    access_token = body.get("access_token", "").strip()
    label = body.get("label", "").strip()

    if not phone_number_id or not access_token:
        raise HTTPException(400, "phone_number_id and access_token required")

    config = _load_config()
    additional = config.get("additional_wa_numbers", [])

    # Check for duplicate
    if any(n["phone_number_id"] == phone_number_id for n in additional):
        raise HTTPException(409, "Phone number already added")

    additional.append({
        "phone_number_id": phone_number_id,
        "access_token": access_token,
        "label": label or phone_number_id,
        "added_at": datetime.now(IST).isoformat(),
    })
    config["additional_wa_numbers"] = additional
    _save_config(config)

    return {"ok": True, "total_numbers": len(additional) + (1 if WHATSAPP_PHONE_NUMBER_ID else 0)}


@app.get("/api/rate-limit/status")
async def api_rate_limit_status(request: Request):
    """Get current WhatsApp API rate limiter status."""
    _check_api_key(request)
    return {
        "daily_used": wa_rate_limiter.daily_used,
        "daily_remaining": wa_rate_limiter.daily_remaining,
        "max_per_day": wa_rate_limiter.config.max_per_day,
        "max_per_second": wa_rate_limiter.config.max_per_second,
    }


@app.put("/api/rate-limit/config")
async def api_update_rate_limit(request: Request):
    """Update WhatsApp rate limiter configuration."""
    _check_api_key(request)
    body = await request.json()
    max_per_second = body.get("max_per_second")
    max_per_day = body.get("max_per_day")
    wa_rate_limiter.update_config(max_per_second=max_per_second, max_per_day=max_per_day)
    return {
        "ok": True,
        "max_per_day": wa_rate_limiter.config.max_per_day,
        "max_per_second": wa_rate_limiter.config.max_per_second,
    }


# ====================================================================
#  FRONTEND SERVING  (React SPA from dashboard/dist/)
# ====================================================================

DASHBOARD_DIR = Path(__file__).parent / "dashboard" / "dist"

# Mount static assets (JS, CSS, images) at /assets
if (DASHBOARD_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIR / "assets")), name="dashboard-assets")

# Serve favicon and other root-level static files
@app.get("/favicon.svg")
@app.get("/favicon.ico")
async def serve_favicon():
    for name in ("favicon.svg", "favicon.ico"):
        fpath = DASHBOARD_DIR / name
        if fpath.exists():
            return FileResponse(str(fpath))
    raise HTTPException(404)

# SPA fallback: catch 404s on non-API GETs and serve index.html for client-side routing.
# This uses Starlette exception handler so it never shadows real API routes.
from starlette.exceptions import HTTPException as StarletteHTTPException

_original_exception_handler = None

@app.exception_handler(StarletteHTTPException)
async def _spa_fallback(request: Request, exc: StarletteHTTPException):
    """If a GET request 404s and isn't an API/webhook path, serve the SPA."""
    path = request.url.path
    if (
        exc.status_code == 404
        and request.method == "GET"
        and not path.startswith(("/api", "/health", "/webhook"))
    ):
        # Try to serve the exact file from dist
        clean = path.lstrip("/")
        requested = DASHBOARD_DIR / clean
        if clean and requested.exists() and requested.is_file():
            return FileResponse(str(requested))
        # Serve SPA index.html
        index = DASHBOARD_DIR / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
    # For all other errors, return the standard JSON error
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.get("/")
async def serve_root():
    """Serve the dashboard root."""
    index = DASHBOARD_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Nazar</h1><p>Dashboard not built. Run <code>cd dashboard && npm run build</code></p>")


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


async def _campaign_scheduler_loop():
    """
    Background loop: execute campaigns whose scheduled_at time has arrived.
    Checks every 30 seconds. Only picks campaigns with status == "scheduled".
    """
    while True:
        try:
            await asyncio.sleep(30)
            now = datetime.now(IST)
            campaigns = get_campaign_history(limit=200)
            for campaign in campaigns:
                if campaign.get("status") != "scheduled":
                    continue
                scheduled_str = campaign.get("scheduled_at", "")
                if not scheduled_str:
                    continue
                try:
                    scheduled_dt = datetime.fromisoformat(scheduled_str)
                    if scheduled_dt.tzinfo is None:
                        scheduled_dt = scheduled_dt.replace(tzinfo=IST)
                    if scheduled_dt <= now:
                        logger.info(f"Executing scheduled campaign: {campaign['id']}")
                        update_campaign(campaign["id"], {"status": "sending"})
                        # Re-send to original contacts
                        contact_ids = campaign.get("contact_ids") or []
                        if contact_ids:
                            targets = [get_contact(cid) for cid in contact_ids]
                            targets = [c for c in targets if c]
                        else:
                            targets = list_contacts(
                                stage=campaign.get("filter_stage") or None,
                                tag=campaign.get("filter_tag") or None,
                            )
                        template = get_template(campaign.get("template_id", ""))
                        if not template or not targets:
                            update_campaign(campaign["id"], {"status": "failed"})
                            continue
                        sent, failed = 0, 0
                        for contact in targets:
                            phone = contact.get("phone", "")
                            if not phone:
                                failed += 1
                                continue
                            phone_e164 = f"+{phone}" if not phone.startswith("+") else phone
                            if not can_message(phone_e164):
                                failed += 1
                                continue
                            try:
                                rendered = render_template(template, contact)
                                # Scheduled campaigns must use template API (outside 24h window)
                                if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID:
                                    components = _build_template_components(template, contact)
                                    result = await send_template_message(
                                        phone,
                                        template.get("name", ""),
                                        template.get("language", "en"),
                                        components=components or None,
                                    )
                                    if "error" in result:
                                        failed += 1
                                        logger.error(
                                            "Scheduled campaign %s: template send failed for %s: %s",
                                            campaign["id"], phone, result["error"].get("message", ""),
                                        )
                                        continue
                                save_message(contact["contact_id"], "outbound", rendered, sent_by="campaign")
                                sent += 1
                            except Exception as exc:
                                failed += 1
                                logger.error(f"Scheduled campaign send error: {exc}")
                            await asyncio.sleep(0.1)
                        update_campaign(campaign["id"], {
                            "status": "completed",
                            "sent": sent,
                            "failed": failed,
                        })
                        log_audit("campaign.sent", "campaign", campaign["id"],
                                  actor_id="scheduler",
                                  details={"sent": sent, "failed": failed, "scheduled": True})
                        logger.info(f"Scheduled campaign {campaign['id']} done: {sent} sent, {failed} failed")
                except Exception as e:
                    logger.error(f"Scheduled campaign {campaign.get('id')} error: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Campaign scheduler loop error: {e}")


async def _memory_maintenance_loop():
    """
    Nightly background loop: prune stale vector memories for all contacts.
    Runs once per day (at process startup offset + 24h).
    """
    # Offset by 1 hour so it doesn't run at startup
    await asyncio.sleep(3600)
    while True:
        try:
            logger.info("Starting nightly memory maintenance...")
            from customer_memory import prune_stale_memories
            contacts = list_contacts()
            pruned_total = 0
            for c in contacts:
                try:
                    n = prune_stale_memories(c["contact_id"])
                    pruned_total += n
                except Exception as e:
                    logger.error(f"Memory pruning failed for {c['contact_id']}: {e}")
            logger.info(f"Memory maintenance done: {pruned_total} entries pruned across {len(contacts)} contacts")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Memory maintenance loop error: {e}")
        await asyncio.sleep(86400)  # Daily


@app.on_event("startup")
async def startup_event():
    """Start background tasks, initialize database, and bootstrap default workspace."""
    # Initialize SQLite database (creates tables if not exist)
    from database import init_db
    init_db()
    logger.info("SQLite database initialized")

    # Load recent message IDs for dedup (prevents duplicates after restart)
    _load_recent_message_ids()

    # Security checks — warn loudly about missing production configuration
    if not os.environ.get("WA_APP_SECRET", ""):
        logger.critical(
            "⚠️  WA_APP_SECRET is not set! All inbound webhooks will be rejected "
            "with HTTP 503 until this is configured. Set WA_APP_SECRET in .env to enable webhook processing."
        )
    if API_KEY == "nazar_dev_key":
        logger.critical(
            "⚠️  NAZAR_API_KEY is still the default 'nazar_dev_key'! "
            "Change it in .env before going to production."
        )
    if not os.environ.get("NAZAR_TOKEN_SECRET", ""):
        logger.warning(
            "NAZAR_TOKEN_SECRET not set — auto-generated. "
            "Set it explicitly in .env for stable sessions across restarts."
        )
    if not os.environ.get("RAZORPAY_WEBHOOK_SECRET", ""):
        logger.warning(
            "RAZORPAY_WEBHOOK_SECRET not set — payment webhooks will be rejected."
        )

    asyncio.create_task(_auto_resume_loop())
    asyncio.create_task(_campaign_scheduler_loop())
    asyncio.create_task(_memory_maintenance_loop())
    logger.info("Background tasks started: auto-resume, campaign scheduler, memory maintenance")

    # Bootstrap default workspace if none exists
    try:
        boot = bootstrap_default_workspace()
        if not boot.get("already_existed"):
            logger.info(
                "Default workspace bootstrapped — "
                "email: admin@nazar.app, password: changeme123"
            )
        # Ensure default workspace has a starter subscription
        ws_id = boot["workspace"]["workspace_id"]
        from billing import get_subscription, create_subscription
        if not get_subscription(ws_id):
            create_subscription(ws_id, "starter", trial=True)
            logger.info(f"Starter trial subscription created for workspace {ws_id}")

        # Sync contact count to billing usage (gauge metric)
        try:
            contacts_count = len(list_contacts())
            set_usage(ws_id, "contacts", contacts_count)
        except Exception:
            pass

        # Ensure default channel exists (backward compatibility)
        if WHATSAPP_PHONE_NUMBER_ID:
            try:
                ensure_default_channel(
                    phone_number_id=WHATSAPP_PHONE_NUMBER_ID,
                    access_token=WHATSAPP_ACCESS_TOKEN,
                    workspace_id=ws_id,
                )
                logger.info("Default channel ensured for phone_number_id=%s", WHATSAPP_PHONE_NUMBER_ID)
            except Exception as e:
                logger.warning("Default channel setup warning: %s", e)

    except Exception as e:
        logger.warning(f"Bootstrap warning (non-fatal): {e}")


# ====================================================================
#  HEALTH CHECK
# ====================================================================

@app.get("/health")
async def health():
    """
    Enhanced health check — verifies storage, vector DB, and configuration.
    Returns "degraded" (HTTP 200) if non-critical checks fail, never 500.
    """
    checks = {}  # type: dict

    # 1. Storage writability
    try:
        test_file = DATA_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["storage"] = "ok"
    except Exception as e:
        checks["storage"] = f"error: {e}"

    # 2. ChromaDB
    try:
        from customer_memory import CHROMADB_AVAILABLE
        if CHROMADB_AVAILABLE:
            import chromadb as _chroma
            _health_path = DATA_DIR / ".chroma_health"
            _health_path.mkdir(parents=True, exist_ok=True)
            _c = _chroma.PersistentClient(path=str(_health_path))
            _c.heartbeat()
            checks["vector_db"] = "ok"
        else:
            checks["vector_db"] = "unavailable (chromadb not installed)"
    except TypeError:
        # Python 3.8 incompatibility with some ChromaDB type annotations
        # ChromaDB is installed and will work at runtime via lazy init
        checks["vector_db"] = "ok (compat mode)"
    except Exception as e:
        checks["vector_db"] = f"error: {e}"

    # 3. LLM providers
    try:
        provider_info = llm_health()
        available = [p for p, v in provider_info.items() if v.get("available")]
        checks["llm"] = f"ok ({len(available)}/{len(provider_info)} providers)"
    except Exception as e:
        checks["llm"] = f"error: {e}"

    # 4. WhatsApp configuration
    checks["whatsapp"] = "configured" if WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID else "not_configured"
    checks["webhook_security"] = "ok" if os.environ.get("WA_APP_SECRET") else "missing_WA_APP_SECRET"

    # 5. Rate limiter
    checks["rate_limiter"] = (
        f"ok ({wa_rate_limiter.daily_used}/{wa_rate_limiter.config.max_per_day} used today)"
    )

    overall = "ok" if all(
        v in ("ok", "configured") or v.startswith("ok")
        for k, v in checks.items()
        if k not in ("whatsapp", "webhook_security")
    ) else "degraded"

    return {
        "status": overall,
        "service": "nazar",
        "timestamp": datetime.now(IST).isoformat(),
        "checks": checks,
    }


# ====================================================================
#  SIMULATION MODE — Test AI without WhatsApp
# ====================================================================

@app.post("/api/simulate")
async def api_simulate(request: Request):
    """
    Simulate a customer message and get the AI reply.
    This runs the full conversation pipeline (SOUL.md + memory + knowledge base)
    but skips WhatsApp entirely.

    Body: { "contact_id": str, "message": str }
    Returns: { "reply": str, "contact_id": str }
    """
    _check_api_key(request)
    body = await request.json()
    contact_id = body.get("contact_id")
    message = body.get("message", "").strip()

    if not message:
        raise HTTPException(400, "message is required")

    if not contact_id:
        raise HTTPException(400, "contact_id is required")

    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        contact = None
    if not contact:
        raise HTTPException(404, "Contact not found")

    # Check if any LLM provider is available
    provider_status = llm_health()
    any_available = any(p.get("available") for p in provider_status.values())
    if not any_available:
        raise HTTPException(
            503,
            "No LLM provider is configured. Add an API key in Settings → API Keys."
        )

    phone = contact.get("phone", "+910000000000")
    config = _load_config()

    # NOTE: Do NOT save_message or memory_add_message here — handle_inbound
    # already does both (steps 2 and 8).  Previously this caused duplicate
    # entries in the messages table and double vector upserts.

    # Run full AI conversation pipeline
    async def llm_call(messages):
        return await call_llm_safe(messages, tier="sonnet", phone=phone)

    try:
        response = await handle_inbound(phone, message, llm_call, config=config)
    except Exception as e:
        logger.error(f"Simulation error: {e}", exc_info=True)
        raise HTTPException(500, f"AI generation failed: {str(e)}")

    return {"reply": response, "contact_id": contact_id}


# ====================================================================
#  API KEY MANAGEMENT
# ====================================================================

@app.get("/api/setup/keys")
async def api_get_keys(request: Request):
    """
    Get which API keys are configured (not the actual values).
    """
    _check_api_key(request)
    env_path = Path(__file__).parent / ".env"

    keys_status = {
        "OPENROUTER_API_KEY": bool(os.environ.get("OPENROUTER_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "GOOGLE_API_KEY": bool(os.environ.get("GOOGLE_API_KEY")),
        "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY")),
        "WA_PHONE_NUMBER_ID": bool(os.environ.get("WA_PHONE_NUMBER_ID")),
        "WA_ACCESS_TOKEN": bool(os.environ.get("WA_ACCESS_TOKEN")),
        "WA_APP_SECRET": bool(os.environ.get("WA_APP_SECRET")),
    }

    # Also return masked values so user sees what's set
    masked = {}
    for key in keys_status:
        val = os.environ.get(key, "")
        if val:
            masked[key] = val[:6] + "..." + val[-4:] if len(val) > 12 else "***configured***"
        else:
            masked[key] = ""

    return {"configured": keys_status, "masked": masked}


@app.post("/api/setup/keys")
async def api_save_keys(request: Request):
    """
    Save API keys to .env file and reload into environment.

    Body: { "keys": { "OPENROUTER_API_KEY": "sk-...", ... } }
    Only non-empty values are written; empty strings clear the key.
    """
    _check_api_key(request)
    body = await request.json()
    new_keys = body.get("keys", {})

    if not new_keys:
        raise HTTPException(400, "No keys provided")

    # Allowed keys (whitelist for security)
    ALLOWED_KEYS = {
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
        "GROQ_API_KEY", "WA_PHONE_NUMBER_ID", "WA_ACCESS_TOKEN", "WA_APP_SECRET",
    }

    env_path = Path(__file__).parent / ".env"

    # Read existing .env content
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Parse existing key-value pairs and comments
    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        # Check if this line sets one of our allowed keys
        matched = False
        for key_name in ALLOWED_KEYS:
            if stripped.startswith(f"{key_name}=") or stripped.startswith(f"# {key_name}="):
                if key_name in new_keys:
                    val = new_keys[key_name].strip()
                    new_lines.append(f"{key_name}={val}")
                    updated_keys.add(key_name)
                    matched = True
                    break
        if not matched:
            new_lines.append(line)

    # Add any new keys that weren't in the file
    for key_name, val in new_keys.items():
        if key_name in ALLOWED_KEYS and key_name not in updated_keys:
            new_lines.append(f"{key_name}={val.strip()}")

    # Write back
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Reload into current process environment
    for key_name in ALLOWED_KEYS:
        if key_name in new_keys:
            val = new_keys[key_name].strip()
            if val:
                os.environ[key_name] = val
            elif key_name in os.environ:
                del os.environ[key_name]

    # Update WhatsApp config vars if changed
    global WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WA_API_URL
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
    WHATSAPP_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
    WA_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    logger.info(f"API keys updated: {list(new_keys.keys())}")
    return {"ok": True, "updated": list(new_keys.keys())}


@app.post("/api/setup/test-llm")
async def api_test_llm(request: Request):
    """
    Test the LLM by sending a simple prompt and verifying a response.
    Returns the provider used and response time.
    """
    _check_api_key(request)

    import time as _time
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant. Reply in exactly one short sentence."},
        {"role": "user", "content": "Say hello and confirm you are working."},
    ]

    start = _time.time()
    try:
        response = await call_llm(test_messages, tier="haiku", timeout=15)
        elapsed_ms = int((_time.time() - start) * 1000)

        return {
            "ok": True,
            "response": response[:200],
            "latency_ms": elapsed_ms,
            "providers": llm_health(),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:300],
            "providers": llm_health(),
        }



# ====================================================================
#  SETUP STATUS
# ====================================================================

ENV_PATH = Path(__file__).parent / ".env"

def _read_env() -> dict:
    """Read .env file into a dict."""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


@app.get("/api/setup/status")
async def api_setup_status(request: Request):
    """Get setup status — which API keys are configured."""
    _check_api_key(request)
    env = _read_env()
    llm_status = llm_health()
    return {
        "whatsapp": {
            "configured": bool(env.get("WA_ACCESS_TOKEN")),
            "phone_number_id": bool(env.get("WA_PHONE_NUMBER_ID")),
        },
        "llm": {
            "openrouter": {
                "configured": bool(env.get("OPENROUTER_API_KEY")),
                "healthy": llm_status.get("openrouter", {}).get("healthy", False),
            },
            "anthropic": {
                "configured": bool(env.get("ANTHROPIC_API_KEY")),
                "healthy": llm_status.get("anthropic", {}).get("healthy", False),
            },
            "google": {
                "configured": bool(env.get("GOOGLE_API_KEY")),
                "healthy": llm_status.get("google", {}).get("healthy", False),
            },
        },
        "groq": {
            "configured": bool(env.get("GROQ_API_KEY")),
        },
        "any_llm_configured": any(
            bool(env.get(k)) for k in ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
        ),
    }


# ====================================================================
#  SIMULATION MODE — Test AI without WhatsApp (full pipeline)
# ====================================================================

@app.post("/api/simulate/message")
async def api_simulate_message(request: Request):
    """
    Simulate an inbound customer message through the full AI pipeline
    (memory, LLM, signals, handoff detection) without WhatsApp.
    """
    _check_api_key(request)
    body = await request.json()
    contact_id = body.get("contact_id", "")
    message = body.get("message", "")

    if not contact_id or not message:
        raise HTTPException(400, "contact_id and message required")

    try:
        contact = get_contact(contact_id)
    except FileNotFoundError:
        raise HTTPException(404, "Contact not found")
    if not contact:
        raise HTTPException(404, "Contact not found")

    phone = contact["phone"]
    config = _load_config()

    # Check if bot is active
    if not is_bot_active(contact_id):
        save_message(contact_id, "inbound", message)
        return {
            "ok": True,
            "mode": "human",
            "message_saved": True,
            "ai_reply": None,
            "info": "Bot is off for this contact (human mode). Message saved.",
        }

    # Check handoff
    recent_messages = []
    try:
        recent_messages = get_conversation_history(contact_id, days=3)
    except Exception:
        pass

    smart_handoff = config.get("smart_handoff", True)

    async def haiku_call(msgs):
        return await call_llm_safe(msgs, tier="haiku", phone=phone)

    handoff_result = await evaluate_handoff(
        contact_id=contact_id,
        message=message,
        recent_messages=recent_messages,
        llm_call=haiku_call if smart_handoff else None,
        contact_name=contact.get("name", ""),
        contact_phone=phone,
        smart_handoff_enabled=smart_handoff,
    )

    if handoff_result:
        save_message(contact_id, "inbound", message)
        handoff_msg = config.get(
            "handoff_message",
            "I'll connect you with a team member who can help with this directly.",
        )
        save_message(contact_id, "outbound", handoff_msg, sent_by="bot")
        return {
            "ok": True,
            "mode": "handoff",
            "handoff_reason": handoff_result.get("reason", ""),
            "ai_reply": handoff_msg,
        }

    # Check reply mode
    reply_mode_info = get_effective_reply_mode(contact_id)
    effective_mode = reply_mode_info["mode"]
    campaign_kb_text = reply_mode_info.get("campaign_kb", "")

    if effective_mode == "human_only":
        save_message(contact_id, "inbound", message)
        return {
            "ok": True,
            "mode": "human_only",
            "message_saved": True,
            "ai_reply": None,
            "reply_mode": reply_mode_info,
            "info": "Reply mode is 'human_only'. Message saved. No AI response generated.",
        }

    if effective_mode == "ai_draft":
        save_message(contact_id, "inbound", message)
        try:
            from conversation import generate_ai_reply
            draft_text = await generate_ai_reply(
                contact_id, message, config=config, campaign_kb=campaign_kb_text
            )
            draft_entry = save_draft(contact_id, draft_text, customer_message=message,
                                     campaign_id=reply_mode_info.get("campaign_id", ""))
            return {
                "ok": True,
                "mode": "ai_draft",
                "ai_reply": draft_text,
                "draft": draft_entry,
                "reply_mode": reply_mode_info,
                "info": "AI draft generated. Review and approve from the conversation.",
            }
        except Exception as e:
            return {"ok": False, "error": f"Draft generation failed: {str(e)}"}

    # auto_ai mode — Normal AI response
    async def llm_call(msgs):
        return await call_llm_safe(msgs, tier="sonnet", phone=phone)

    try:
        response = await handle_inbound(phone, message, llm_call, config, campaign_kb=campaign_kb_text)
    except Exception as e:
        logger.error(f"Simulate message error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

    # Check AI self-handoff
    response_handoff = await evaluate_response_handoff(
        contact_id=contact_id,
        ai_response=response,
        contact_name=contact.get("name", ""),
        contact_phone=phone,
    )

    return {
        "ok": True,
        "mode": "bot",
        "ai_reply": response,
        "reply_mode": reply_mode_info,
        "handoff_triggered": response_handoff is not None,
        "handoff_reason": response_handoff.get("reason") if response_handoff else None,
    }


# ====================================================================
#  MAIN
# ====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    logger.info(f"Starting Nazar on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
