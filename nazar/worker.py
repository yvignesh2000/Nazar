"""
Nazar background worker.

Processes queued broadcasts, inbound WhatsApp events, and AI generation jobs.
"""

from __future__ import annotations

import asyncio
import logging
import os

from core.ai_jobs import generate_followup_draft, generate_reply_suggestion, refresh_contact_summary
from core.contact_manager import (
    get_contact,
    get_conversation_history,
    get_conversation_record,
    list_contacts,
    mark_conversation_handoff_required,
    save_message,
    set_conversation_use_case,
)
from core.conversation import (
    generate_reply_for_contact,
    get_or_create_contact_for_phone,
    persist_memory_and_signals,
    should_handoff,
)
from core.job_queue import claim_due_jobs, complete_job, fail_job
from core.llm_router import call_llm_safe
from core.outbound import log_broadcast
from core.policy_store import resolve_reply_policy, should_force_human
from core.transcription import TranscriptionError, transcribe_audio
from core.workspace_store import get_workspace_config
from server import download_whatsapp_media, send_template_message, send_whatsapp_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nazar.worker")

HANDOFF_MESSAGE = "I'll connect you with a team member who can help. They'll be with you shortly!"
TRANSCRIPTION_FAILURE_MESSAGE = "I couldn't process that voice note. Could you type it out instead?"


def _extract_wa_message_id(response: dict) -> str:
    return ((response.get("messages") or [{}])[0]).get("id", "")


async def _llm_call(messages, phone: str = ""):
    return await call_llm_safe(messages, tier="sonnet", phone=phone)


async def _send_ai_reply(contact: dict, conversation: dict, inbound_message: str) -> dict:
    config = get_workspace_config()
    response_text = await generate_reply_for_contact(
        contact["contact_id"],
        inbound_message,
        lambda messages: _llm_call(messages, phone=contact.get("phone", "")),
        config=config,
        include_current_message=False,
    )
    wa_response = await send_whatsapp_message(contact["phone"], response_text)
    wa_message_id = _extract_wa_message_id(wa_response)
    save_message(
        conversation["conversation_id"],
        "outbound",
        response_text,
        sent_by="bot",
        wa_message_id=wa_message_id,
    )
    persist_memory_and_signals(contact["contact_id"], contact, inbound_message, response_text)
    return {
        "contact_id": contact["contact_id"],
        "conversation_id": conversation["conversation_id"],
        "reply": response_text,
        "wa_message_id": wa_message_id,
    }


async def _generate_bot_assist_reply(contact: dict, inbound_message: str) -> str:
    config = get_workspace_config()
    return await generate_reply_for_contact(
        contact["contact_id"],
        inbound_message,
        lambda messages: _llm_call(messages, phone=contact.get("phone", "")),
        config=config,
        include_current_message=False,
    )


async def _process_saved_inbound_text(payload: dict) -> dict:
    contact_id = payload.get("contact_id")
    conversation_id = payload.get("conversation_id")
    inbound_message = (payload.get("message") or "").strip()
    if not contact_id or not conversation_id or not inbound_message:
        raise ValueError("Inbound text job missing contact_id, conversation_id, or message")

    contact = get_contact(contact_id)
    conversation = get_conversation_record(conversation_id)
    if not contact or not conversation:
        raise ValueError("Inbound text job references missing contact or conversation")
    policy = resolve_reply_policy(conversation.get("active_reply_policy_key") or conversation.get("use_case_key"))
    if conversation.get("human_queue") != policy.get("fallback_queue"):
        conversation = set_conversation_use_case(
            conversation_id,
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
    if not conversation.get("bot_mode", True):
        return {"skipped": True, "reason": "bot_mode_off", "contact_id": contact_id}
    if policy.get("reply_mode") == "bot_assist":
        updated = mark_conversation_handoff_required(conversation_id, True)
        updated = set_conversation_use_case(
            conversation_id,
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        suggested_reply = await _generate_bot_assist_reply(contact, inbound_message)
        return {
            "contact_id": contact_id,
            "conversation_id": conversation_id,
            "bot_assist": True,
            "suggested_reply": suggested_reply,
            "policy": policy,
            "human_queue": updated.get("human_queue"),
        }
    if policy.get("reply_mode") in {"human_first", "manual_only"} or should_force_human(policy, inbound_message) or should_handoff(inbound_message):
        updated = mark_conversation_handoff_required(conversation_id, True)
        updated = set_conversation_use_case(
            conversation_id,
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        handoff_message_id = ""
        if policy.get("reply_mode") != "manual_only":
            handoff_response = await send_whatsapp_message(contact["phone"], HANDOFF_MESSAGE)
            handoff_message_id = _extract_wa_message_id(handoff_response)
            save_message(
                conversation_id,
                "outbound",
                HANDOFF_MESSAGE,
                sent_by="bot",
                wa_message_id=handoff_message_id,
            )
        return {
            "contact_id": contact_id,
            "conversation_id": conversation_id,
            "handoff_required": True,
            "policy": policy,
            "human_queue": updated.get("human_queue"),
            "wa_message_id": handoff_message_id,
            "status": updated.get("status"),
        }
    return await _send_ai_reply(contact, conversation, inbound_message)


async def _process_inbound_voice(payload: dict) -> dict:
    phone = (payload.get("phone") or "").strip()
    media_id = (payload.get("media_id") or "").strip()
    wa_message_id = (payload.get("wa_message_id") or "").strip()
    if not phone or not media_id:
        raise ValueError("Inbound voice job missing phone or media_id")

    try:
        audio_bytes, mime_type = await download_whatsapp_media(media_id)
        transcript = await transcribe_audio(audio_bytes, mime_type)
    except TranscriptionError:
        await send_whatsapp_message(phone, TRANSCRIPTION_FAILURE_MESSAGE)
        return {"phone": phone, "transcription_failed": True}

    contact = get_or_create_contact_for_phone(phone)
    inbound_record = save_message(contact["contact_id"], "inbound", transcript, wa_message_id=wa_message_id)
    conversation = get_conversation_record(inbound_record["conversation_id"])
    if not conversation:
        raise ValueError("Voice job failed to resolve conversation after saving transcript")
    policy = resolve_reply_policy(conversation.get("active_reply_policy_key") or conversation.get("use_case_key"))
    if conversation.get("human_queue") != policy.get("fallback_queue"):
        conversation = set_conversation_use_case(
            conversation["conversation_id"],
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
    if not conversation.get("bot_mode", True):
        return {
            "contact_id": contact["contact_id"],
            "conversation_id": conversation["conversation_id"],
            "transcript": transcript,
            "skipped": True,
            "reason": "bot_mode_off",
        }
    if policy.get("reply_mode") == "bot_assist":
        updated = mark_conversation_handoff_required(conversation["conversation_id"], True)
        updated = set_conversation_use_case(
            conversation["conversation_id"],
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        suggested_reply = await _generate_bot_assist_reply(contact, transcript)
        return {
            "contact_id": contact["contact_id"],
            "conversation_id": conversation["conversation_id"],
            "transcript": transcript,
            "bot_assist": True,
            "suggested_reply": suggested_reply,
            "policy": policy,
            "human_queue": updated.get("human_queue"),
        }
    if policy.get("reply_mode") in {"human_first", "manual_only"} or should_force_human(policy, transcript) or should_handoff(transcript):
        updated = mark_conversation_handoff_required(conversation["conversation_id"], True)
        updated = set_conversation_use_case(
            conversation["conversation_id"],
            conversation.get("use_case_key") or policy["use_case_key"],
            source_type=conversation.get("source_type"),
            source_ref=conversation.get("source_ref"),
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        handoff_message_id = ""
        if policy.get("reply_mode") != "manual_only":
            handoff_response = await send_whatsapp_message(contact["phone"], HANDOFF_MESSAGE)
            handoff_message_id = _extract_wa_message_id(handoff_response)
            save_message(
                conversation["conversation_id"],
                "outbound",
                HANDOFF_MESSAGE,
                sent_by="bot",
                wa_message_id=handoff_message_id,
            )
        return {
            "contact_id": contact["contact_id"],
            "conversation_id": conversation["conversation_id"],
            "transcript": transcript,
            "handoff_required": True,
            "policy": policy,
            "human_queue": updated.get("human_queue"),
            "wa_message_id": handoff_message_id,
            "status": updated.get("status"),
        }
    result = await _send_ai_reply(contact, conversation, transcript)
    result["transcript"] = transcript
    return result


async def _execute_broadcast(job: dict) -> dict:
    payload = job.get("payload") or {}
    message = (payload.get("message") or "").strip()
    template_name = (payload.get("template") or "").strip()
    filter_stage = payload.get("stage")
    filter_tag = payload.get("tag")
    contact_ids = payload.get("contact_ids") or []
    reply_use_case_key = (payload.get("reply_use_case_key") or "broadcast_reply").strip() or "broadcast_reply"
    policy = resolve_reply_policy(reply_use_case_key)

    if not message and not template_name:
        raise ValueError("Broadcast job missing message or template")

    if contact_ids:
        targets = [get_contact(contact_id) for contact_id in contact_ids]
        targets = [contact for contact in targets if contact]
    else:
        targets = list_contacts(stage=filter_stage, tag=filter_tag)

    results = {"sent": 0, "failed": 0, "details": []}
    for contact in targets:
        phone = contact["phone"]
        try:
            if template_name:
                response = await send_template_message(phone, template_name)
                body = f"[template: {template_name}]"
                wa_message_id = _extract_wa_message_id(response)
            else:
                response = await send_whatsapp_message(phone, message)
                body = message
                wa_message_id = _extract_wa_message_id(response)
            outbound_record = save_message(contact["contact_id"], "outbound", body, sent_by="broadcast", wa_message_id=wa_message_id)
            set_conversation_use_case(
                outbound_record["conversation_id"],
                reply_use_case_key,
                source_type="broadcast",
                source_ref=job["id"],
                active_reply_policy_key=policy["use_case_key"],
                human_queue=policy.get("fallback_queue"),
            )
            results["sent"] += 1
            results["details"].append({"phone": phone, "status": "sent"})
        except Exception as exc:
            results["failed"] += 1
            results["details"].append({"phone": phone, "status": "failed", "error": str(exc)})
        await asyncio.sleep(0.1)

    log_broadcast(
        message=message,
        template_name=template_name,
        target_count=len(targets),
        sent=results["sent"],
        failed=results["failed"],
        filter_stage=filter_stage,
        filter_tag=filter_tag,
    )
    return results


async def _execute_ai_reply_suggestion(payload: dict) -> dict:
    contact_id = payload.get("contact_id")
    message = (payload.get("message") or "").strip()
    if not contact_id or not message:
        raise ValueError("AI reply job missing contact_id or message")
    return await generate_reply_suggestion(contact_id, message)


async def _execute_followup_draft(payload: dict) -> dict:
    contact_id = payload.get("contact_id")
    contact = get_contact(contact_id) if contact_id else None
    if not contact:
        raise ValueError("Follow-up job missing valid contact")
    draft = await generate_followup_draft(contact)
    return {"contact_id": contact_id, "draft": draft}


async def _execute_contact_summary(payload: dict) -> dict:
    contact_id = payload.get("contact_id")
    contact = get_contact(contact_id) if contact_id else None
    if not contact:
        raise ValueError("Summary job missing valid contact")
    recent_messages = get_conversation_history(contact_id, days=30)
    summary = await refresh_contact_summary(contact, recent_messages)
    summary["contact_id"] = contact_id
    return summary


async def process_job(job: dict) -> dict:
    kind = job.get("kind")
    payload = job.get("payload") or {}
    if kind == "broadcast_send":
        return await _execute_broadcast(job)
    if kind == "process_saved_inbound_text":
        return await _process_saved_inbound_text(payload)
    if kind == "process_inbound_voice":
        return await _process_inbound_voice(payload)
    if kind == "ai_reply_suggestion":
        return await _execute_ai_reply_suggestion(payload)
    if kind == "contact_followup_draft":
        return await _execute_followup_draft(payload)
    if kind == "contact_summary_refresh":
        return await _execute_contact_summary(payload)
    raise ValueError(f"Unsupported job kind: {kind}")


async def process_available_jobs_once(limit: int = 10) -> list[dict]:
    jobs = claim_due_jobs(limit=limit)
    results = []
    for job in jobs:
        logger.info("Processing job %s (%s)", job["id"], job["kind"])
        try:
            result = await process_job(job)
            complete_job(job["id"], result=result)
            results.append({"job_id": job["id"], "status": "completed", "result": result})
        except Exception as exc:
            logger.exception("Job %s failed", job["id"])
            fail_job(job["id"], str(exc), retry_delay_seconds=30)
            results.append({"job_id": job["id"], "status": "failed", "error": str(exc)})
    return results


async def run_worker_loop() -> None:
    poll_interval = float(os.environ.get("NAZAR_WORKER_POLL_SECONDS", "2"))
    batch_size = int(os.environ.get("NAZAR_WORKER_BATCH_SIZE", "5"))
    logger.info("Nazar worker started")
    while True:
        results = await process_available_jobs_once(limit=batch_size)
        if not results:
            await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
