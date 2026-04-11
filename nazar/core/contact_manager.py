"""
Nazar — Contact manager and conversation-first inbox store.

This module keeps the current CRM and inbox API surface mostly compatible
while shifting persistence to normalized conversation records.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select

from db import (
    Contact,
    ContactNote,
    Conversation,
    ConversationMessage,
    MessageStatusEvent,
    User,
    Workspace,
    WorkspaceMembership,
    default_workspace_slug,
    init_db,
    session_scope,
)

try:
    from encryption import decrypt_file, decrypt_json
except Exception:
    decrypt_file = None
    decrypt_json = None

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
PIPELINE_STAGES = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
CONVERSATION_STATUSES = ["open", "needs_reply", "snoozed", "closed"]
LEGACY_CONTACTS_DIR = Path(__file__).parent.parent / "data" / "contacts"
_storage_initialized = False

_CONTACT_FIELDS = {
    "name",
    "phone",
    "company",
    "source",
    "assigned_to",
    "pipeline_stage",
    "deal_value",
    "lead_score",
    "tags",
    "last_contacted_at",
    "last_replied_at",
    "total_messages",
    "opt_in",
    "opt_in_date",
    "created_at",
    "notes",
}


def infer_contact_channel(phone: str, source: Optional[str] = None) -> str:
    raw = str(phone or "").strip().lower()
    src = str(source or "").strip().lower()
    if raw.startswith("telegram:") or src.startswith("telegram"):
        return "telegram"
    return "whatsapp"


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone or "")
    if cleaned and cleaned[0] != "+" and cleaned[0].isdigit():
        cleaned = "+" + cleaned
    return cleaned


def _now() -> datetime:
    return datetime.now(IST)


def _parse_dt(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=IST)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _tags_to_json(tags: Optional[list]) -> str:
    return json.dumps([str(tag) for tag in (tags or [])], ensure_ascii=False)


def _tags_from_json(raw: str) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _workspace_id(session) -> str:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace.id


def _serialize_contact(contact: Contact) -> dict:
    channel = infer_contact_channel(contact.phone, contact.source)
    return {
        "contact_id": contact.id,
        "name": contact.name or "",
        "phone": contact.phone,
        "channel": channel,
        "company": contact.company,
        "pipeline_stage": contact.pipeline_stage,
        "deal_value": float(contact.deal_value or 0),
        "lead_score": int(contact.lead_score or 0),
        "assigned_to": contact.assigned_to,
        "tags": _tags_from_json(contact.tags_json),
        "source": contact.source,
        "last_contacted_at": _to_iso(contact.last_contacted_at),
        "last_replied_at": _to_iso(contact.last_replied_at),
        "total_messages": int(contact.total_messages or 0),
        "opt_in": bool(contact.opt_in),
        "opt_in_date": _to_iso(contact.opt_in_date),
        "created_at": _to_iso(contact.created_at),
        "notes": contact.notes or "",
    }


def _serialize_message(message: ConversationMessage) -> dict:
    return {
        "message_id": message.id,
        "conversation_id": message.conversation_id,
        "contact_id": message.contact_id,
        "timestamp": _to_iso(message.timestamp),
        "direction": message.direction,
        "content": message.content,
        "sent_by": message.sent_by,
        "wa_message_id": message.wa_message_id,
        "delivery_status": message.delivery_status,
    }


def _serialize_conversation(conversation: Conversation, contact: Contact) -> dict:
    assigned_name = conversation.assigned_user.name if conversation.assigned_user is not None else None
    channel = infer_contact_channel(contact.phone, contact.source)
    return {
        "conversation_id": conversation.id,
        "contact_id": contact.id,
        "name": contact.name or "Unknown",
        "phone": contact.phone,
        "channel": channel,
        "stage": contact.pipeline_stage,
        "tags": _tags_from_json(contact.tags_json),
        "lead_score": int(contact.lead_score or 0),
        "message_count": int(contact.total_messages or 0),
        "bot_mode": bool(conversation.bot_mode),
        "status": conversation.status,
        "handoff_required": bool(conversation.handoff_required),
        "assigned_user_id": conversation.assigned_user_id,
        "assigned_user_name": assigned_name,
        "use_case_key": conversation.use_case_key or "default_inbound",
        "source_type": conversation.source_type or "direct_inbound",
        "source_ref": conversation.source_ref,
        "active_reply_policy_key": conversation.active_reply_policy_key or conversation.use_case_key or "default_inbound",
        "human_queue": conversation.human_queue,
        "ai_assist_status": conversation.ai_assist_status,
        "ai_assist_draft": conversation.ai_assist_draft or "",
        "ai_assist_updated_at": _to_iso(conversation.ai_assist_updated_at),
        "last_time": _to_iso(conversation.last_message_at),
        "last_inbound_at": _to_iso(conversation.last_inbound_at),
        "last_outbound_at": _to_iso(conversation.last_outbound_at),
        "last_message_preview": conversation.last_message_preview or "",
    }


def _load_legacy_phone_index() -> dict:
    index_path = LEGACY_CONTACTS_DIR / ".phone_index.json"
    if not index_path.exists():
        return {}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read legacy phone index: {exc}")
        return {}


def _contact_by_id(session, contact_id: str) -> Optional[Contact]:
    return session.execute(select(Contact).where(Contact.id == contact_id)).scalar_one_or_none()


def _contact_by_phone(session, phone: str) -> Optional[Contact]:
    workspace_id = _workspace_id(session)
    return session.execute(
        select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == phone)
    ).scalar_one_or_none()


def _conversation_for_contact(session, contact_id: str) -> Optional[Conversation]:
    return session.execute(select(Conversation).where(Conversation.contact_id == contact_id)).scalar_one_or_none()


def _conversation_by_id(session, conversation_id: str) -> Optional[Conversation]:
    return session.execute(select(Conversation).where(Conversation.id == conversation_id)).scalar_one_or_none()


def _resolve_conversation(session, identifier: str) -> Optional[Conversation]:
    conversation = _conversation_by_id(session, identifier)
    if conversation is not None:
        return conversation
    contact = _contact_by_id(session, identifier)
    if contact is not None:
        return _ensure_conversation(session, contact)
    return None


def _ensure_conversation(session, contact: Contact) -> Conversation:
    conversation = _conversation_for_contact(session, contact.id)
    if conversation is None:
        last_message_at = contact.last_replied_at or contact.last_contacted_at or contact.created_at
        conversation = Conversation(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            status="open",
            bot_mode=True,
            handoff_required=False,
            use_case_key="default_inbound",
            source_type="direct_inbound",
            source_ref=None,
            active_reply_policy_key="default_inbound",
            human_queue="sales",
            ai_assist_status=None,
            ai_assist_draft=None,
            ai_assist_updated_at=None,
            last_message_at=last_message_at,
            last_inbound_at=contact.last_replied_at,
            last_outbound_at=contact.last_contacted_at,
            last_message_preview="",
            created_at=contact.created_at or _now(),
            updated_at=_now(),
        )
        session.add(conversation)
        session.flush()
    return conversation


def _update_conversation_state_for_message(conversation: Conversation, direction: str, content: str, timestamp: datetime):
    conversation.last_message_at = timestamp
    conversation.updated_at = timestamp
    conversation.last_message_preview = (content or "")[:120]
    if direction == "inbound":
        conversation.last_inbound_at = timestamp
        conversation.status = "needs_reply"
    else:
        conversation.last_outbound_at = timestamp
        if conversation.status != "snoozed":
            conversation.status = "open"


def _conversation_contact(session, conversation: Conversation) -> Contact:
    contact = _contact_by_id(session, conversation.contact_id)
    if contact is None:
        raise FileNotFoundError(f"Contact {conversation.contact_id} not found")
    return contact


def _load_author_name(session, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    return user.name if user else None


def _extract_mentions(body: str) -> list[str]:
    return sorted(set(re.findall(r"@([A-Za-z0-9._-]+)", body or "")))


def _migrate_legacy_storage_if_needed() -> None:
    if decrypt_json is None or decrypt_file is None:
        return

    phone_index = _load_legacy_phone_index()
    if not phone_index:
        return

    with session_scope() as session:
        existing = session.execute(select(func.count()).select_from(Contact)).scalar_one()
        if existing:
            return

        workspace_id = _workspace_id(session)
        imported_contacts = 0
        imported_messages = 0

        for contact_id, phone in phone_index.items():
            profile_path = LEGACY_CONTACTS_DIR / contact_id / "profile.json.enc"
            if not profile_path.exists():
                continue

            try:
                profile = decrypt_json(phone, profile_path)
            except Exception as exc:
                logger.warning(f"Skipping legacy contact {contact_id}: {exc}")
                continue

            pipeline_stage = profile.get("pipeline_stage") or "New"
            if pipeline_stage not in PIPELINE_STAGES:
                pipeline_stage = "New"

            contact = Contact(
                id=profile.get("contact_id") or contact_id,
                workspace_id=workspace_id,
                name=profile.get("name") or "",
                phone=normalize_phone(profile.get("phone") or phone),
                company=profile.get("company"),
                source=profile.get("source"),
                assigned_to=profile.get("assigned_to"),
                pipeline_stage=pipeline_stage,
                deal_value=float(profile.get("deal_value") or 0),
                lead_score=int(profile.get("lead_score") or 0),
                tags_json=_tags_to_json(profile.get("tags") or []),
                last_contacted_at=_parse_dt(profile.get("last_contacted_at")),
                last_replied_at=_parse_dt(profile.get("last_replied_at")),
                total_messages=int(profile.get("total_messages") or 0),
                opt_in=bool(profile.get("opt_in")),
                opt_in_date=_parse_dt(profile.get("opt_in_date")),
                created_at=_parse_dt(profile.get("created_at")) or _now(),
                notes=profile.get("notes") or "",
            )
            session.add(contact)
            session.flush()
            conversation = _ensure_conversation(session, contact)
            imported_contacts += 1

            conv_dir = LEGACY_CONTACTS_DIR / contact_id / "conversations"
            for conv_file in sorted(conv_dir.glob("*.jsonl.enc")) if conv_dir.exists() else []:
                try:
                    raw = decrypt_file(phone, conv_file)
                except Exception as exc:
                    logger.warning(f"Skipping legacy conversation {conv_file.name} for {contact_id}: {exc}")
                    continue

                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = _parse_dt(payload.get("timestamp")) or _now()
                    session.add(
                        ConversationMessage(
                            workspace_id=workspace_id,
                            conversation_id=conversation.id,
                            contact_id=contact.id,
                            timestamp=timestamp,
                            direction=payload.get("direction") or "inbound",
                            content=payload.get("content") or "",
                            sent_by=payload.get("sent_by") or "bot",
                            wa_message_id=payload.get("wa_message_id"),
                            delivery_status=payload.get("delivery_status"),
                        )
                    )
                    _update_conversation_state_for_message(
                        conversation,
                        payload.get("direction") or "inbound",
                        payload.get("content") or "",
                        timestamp,
                    )
                    imported_messages += 1

        if imported_contacts:
            logger.info(
                f"Migrated legacy CRM data into database: "
                f"{imported_contacts} contacts, {imported_messages} messages"
            )


def initialize_storage() -> None:
    global _storage_initialized
    if _storage_initialized:
        return
    init_db()
    _migrate_legacy_storage_if_needed()
    _storage_initialized = True


def create_contact(
    name: str,
    phone: str,
    company: Optional[str] = None,
    source: Optional[str] = None,
    assigned_to: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    initialize_storage()
    phone = normalize_phone(phone)
    with session_scope() as session:
        workspace_id = _workspace_id(session)
        existing = session.execute(
            select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == phone)
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Contact with phone {phone} already exists")

        contact = Contact(
            id=uuid.uuid4().hex[:12],
            workspace_id=workspace_id,
            name=name or "",
            phone=phone,
            company=company,
            source=source,
            assigned_to=assigned_to,
            pipeline_stage="New",
            deal_value=0.0,
            lead_score=0,
            tags_json=_tags_to_json(tags),
            total_messages=0,
            opt_in=False,
            created_at=_now(),
            notes="",
        )
        session.add(contact)
        session.flush()
        _ensure_conversation(session, contact)
        logger.info(f"Created contact: {contact.id} ({contact.name}, {contact.phone})")
        return _serialize_contact(contact)


def get_contact(contact_id: str) -> Optional[dict]:
    initialize_storage()
    with session_scope() as session:
        contact = _contact_by_id(session, contact_id)
        return _serialize_contact(contact) if contact else None


def update_contact(contact_id: str, **fields) -> dict:
    initialize_storage()
    unknown_fields = set(fields) - _CONTACT_FIELDS
    if unknown_fields:
        raise ValueError(f"Unsupported contact fields: {sorted(unknown_fields)}")

    with session_scope() as session:
        contact = _contact_by_id(session, contact_id)
        if contact is None:
            raise FileNotFoundError(f"Contact {contact_id} not found")

        if "phone" in fields:
            new_phone = normalize_phone(fields["phone"])
            duplicate = session.execute(
                select(Contact).where(
                    Contact.workspace_id == contact.workspace_id,
                    Contact.phone == new_phone,
                    Contact.id != contact_id,
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ValueError(f"Contact with phone {new_phone} already exists")
            contact.phone = new_phone

        if "pipeline_stage" in fields:
            stage = fields["pipeline_stage"]
            if stage not in PIPELINE_STAGES:
                raise ValueError(f"Invalid pipeline stage '{stage}'. Must be one of: {PIPELINE_STAGES}")
            contact.pipeline_stage = stage

        if "lead_score" in fields:
            score = fields["lead_score"]
            if not isinstance(score, (int, float)) or score < 0 or score > 100:
                raise ValueError("lead_score must be between 0 and 100")
            contact.lead_score = int(score)

        if "tags" in fields:
            tags = fields["tags"]
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            contact.tags_json = _tags_to_json(tags)

        for field_name in ("name", "company", "source", "assigned_to", "notes"):
            if field_name in fields:
                setattr(contact, field_name, fields[field_name])

        if "deal_value" in fields:
            contact.deal_value = float(fields["deal_value"] or 0)
        if "total_messages" in fields:
            contact.total_messages = int(fields["total_messages"] or 0)
        if "opt_in" in fields:
            contact.opt_in = bool(fields["opt_in"])

        for field_name in ("last_contacted_at", "last_replied_at", "opt_in_date", "created_at"):
            if field_name in fields:
                setattr(contact, field_name, _parse_dt(fields[field_name]))

        logger.info(f"Updated contact {contact.id}: {sorted(fields.keys())}")
        return _serialize_contact(contact)


def delete_contact(contact_id: str):
    initialize_storage()
    with session_scope() as session:
        contact = _contact_by_id(session, contact_id)
        if contact is not None:
            session.delete(contact)
            logger.info(f"Deleted contact: {contact_id}")


def list_contacts(stage: Optional[str] = None, assigned_to: Optional[str] = None, tag: Optional[str] = None) -> list:
    initialize_storage()
    with session_scope() as session:
        workspace_id = _workspace_id(session)
        query = select(Contact).where(Contact.workspace_id == workspace_id)
        if stage:
            query = query.where(Contact.pipeline_stage == stage)
        if assigned_to:
            query = query.where(Contact.assigned_to == assigned_to)
        contacts = session.execute(query.order_by(Contact.created_at.desc())).scalars().all()
        serialized = [_serialize_contact(contact) for contact in contacts]
        if tag:
            serialized = [contact for contact in serialized if tag in contact["tags"]]
        return serialized


def get_contact_by_phone(phone: str) -> Optional[dict]:
    initialize_storage()
    phone = normalize_phone(phone)
    with session_scope() as session:
        contact = _contact_by_phone(session, phone)
        return _serialize_contact(contact) if contact else None


def contact_exists(phone: str) -> bool:
    return get_contact_by_phone(phone) is not None


def move_stage(contact_id: str, new_stage: str) -> dict:
    if new_stage not in PIPELINE_STAGES:
        raise ValueError(f"Invalid pipeline stage '{new_stage}'. Must be one of: {PIPELINE_STAGES}")
    return update_contact(contact_id, pipeline_stage=new_stage)


def update_lead_score(contact_id: str, score: int) -> dict:
    return update_contact(contact_id, lead_score=score)


def add_tag(contact_id: str, tag: str) -> dict:
    contact = get_contact(contact_id)
    if contact is None:
        raise FileNotFoundError(f"Contact {contact_id} not found")
    tags = contact.get("tags", [])
    if tag not in tags:
        tags.append(tag)
    return update_contact(contact_id, tags=tags)


def remove_tag(contact_id: str, tag: str) -> dict:
    contact = get_contact(contact_id)
    if contact is None:
        raise FileNotFoundError(f"Contact {contact_id} not found")
    tags = [existing for existing in contact.get("tags", []) if existing != tag]
    return update_contact(contact_id, tags=tags)


def get_pipeline_summary() -> dict:
    summary = {stage: {"count": 0, "total_value": 0.0} for stage in PIPELINE_STAGES}
    for contact in list_contacts():
        stage = contact.get("pipeline_stage", "New")
        if stage in summary:
            summary[stage]["count"] += 1
            summary[stage]["total_value"] += float(contact.get("deal_value") or 0)
    return summary


def save_message(
    contact_or_conversation_id: str,
    direction: str,
    content: str,
    sent_by: str = "bot",
    wa_message_id: Optional[str] = None,
) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, contact_or_conversation_id)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {contact_or_conversation_id} not found")
        contact = _conversation_contact(session, conversation)

        timestamp = _now()
        message = ConversationMessage(
            workspace_id=contact.workspace_id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            timestamp=timestamp,
            direction=direction,
            content=content,
            sent_by=sent_by,
            wa_message_id=wa_message_id,
        )
        session.add(message)

        contact.total_messages = int(contact.total_messages or 0) + 1
        if direction == "outbound":
            contact.last_contacted_at = timestamp
            conversation.ai_assist_draft = None
            conversation.ai_assist_status = None
            conversation.ai_assist_updated_at = None
        elif direction == "inbound":
            contact.last_replied_at = timestamp

        _update_conversation_state_for_message(conversation, direction, content, timestamp)
        session.flush()
        return _serialize_message(message)


def _messages_for_conversation(session, conversation: Conversation, days: int) -> list[ConversationMessage]:
    earliest_day = (_now() - timedelta(days=max(1, int(days)) - 1)).date()
    start_dt = datetime.combine(earliest_day, time.min, tzinfo=IST)
    return session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.timestamp >= start_dt,
        )
        .order_by(ConversationMessage.timestamp.asc(), ConversationMessage.id.asc())
    ).scalars().all()


def get_today_conversation(contact_or_conversation_id: str) -> list:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, contact_or_conversation_id)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {contact_or_conversation_id} not found")
        start_of_day = datetime.combine(_now().date(), time.min, tzinfo=IST)
        messages = session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.timestamp >= start_of_day,
            )
            .order_by(ConversationMessage.timestamp.asc(), ConversationMessage.id.asc())
        ).scalars().all()
        return [_serialize_message(message) for message in messages]


def get_conversation_history(contact_or_conversation_id: str, days: int = 7) -> list:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, contact_or_conversation_id)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {contact_or_conversation_id} not found")
        return [_serialize_message(message) for message in _messages_for_conversation(session, conversation, days)]


def list_contact_notes(contact_id: str, limit: int = 50) -> list:
    initialize_storage()
    with session_scope() as session:
        contact = _contact_by_id(session, contact_id)
        if contact is None:
            raise FileNotFoundError(f"Contact {contact_id} not found")
        notes = session.execute(
            select(ContactNote)
            .where(ContactNote.contact_id == contact_id)
            .order_by(ContactNote.created_at.desc(), ContactNote.id.desc())
            .limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [
            {
                "id": note.id,
                "contact_id": note.contact_id,
                "body": note.body,
                "author_user_id": note.author_user_id,
                "author_name": _load_author_name(session, note.author_user_id),
                "mentions": _extract_mentions(note.body),
                "created_at": _to_iso(note.created_at),
            }
            for note in notes
        ]


def add_contact_note(contact_id: str, body: str, author_user_id: Optional[str] = None) -> dict:
    initialize_storage()
    if not body or not body.strip():
        raise ValueError("Note body is required")
    with session_scope() as session:
        contact = _contact_by_id(session, contact_id)
        if contact is None:
            raise FileNotFoundError(f"Contact {contact_id} not found")
        note = ContactNote(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            author_user_id=author_user_id,
            body=body.strip(),
            created_at=_now(),
        )
        session.add(note)
        session.flush()
        return {
            "id": note.id,
            "contact_id": note.contact_id,
            "body": note.body,
            "author_user_id": note.author_user_id,
            "author_name": _load_author_name(session, note.author_user_id),
            "mentions": _extract_mentions(note.body),
            "created_at": _to_iso(note.created_at),
        }


def get_conversation_record(identifier: str) -> Optional[dict]:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            return None
        contact = _conversation_contact(session, conversation)
        record = _serialize_conversation(conversation, contact)
        record["last_message"] = conversation.last_message_preview or ""
        return record


def list_conversation_records(
    status: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    only_unassigned: bool = False,
    only_human_required: bool = False,
    only_needs_reply: bool = False,
    queue: Optional[str] = None,
    source_type: Optional[str] = None,
    require_ai_assist: bool = False,
) -> list:
    initialize_storage()
    with session_scope() as session:
        workspace_id = _workspace_id(session)
        query = select(Conversation).where(Conversation.workspace_id == workspace_id)
        if status:
            query = query.where(Conversation.status == status)
        if assigned_user_id:
            query = query.where(Conversation.assigned_user_id == assigned_user_id)
        if only_unassigned:
            query = query.where(Conversation.assigned_user_id.is_(None))
        if only_human_required:
            query = query.where((Conversation.bot_mode.is_(False)) | (Conversation.handoff_required.is_(True)))
        if only_needs_reply:
            query = query.where(Conversation.status == "needs_reply")
        if queue:
            query = query.where(Conversation.human_queue == queue)
        if source_type:
            query = query.where(Conversation.source_type == source_type)
        if require_ai_assist:
            query = query.where(Conversation.ai_assist_status == "available")
        conversations = session.execute(
            query.order_by(Conversation.last_message_at.desc(), Conversation.updated_at.desc())
        ).scalars().all()
        records = []
        for conversation in conversations:
            contact = _conversation_contact(session, conversation)
            record = _serialize_conversation(conversation, contact)
            record["last_message"] = conversation.last_message_preview or ""
            records.append(record)
        return records


def set_conversation_bot_mode(identifier: str, bot_on: bool) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        conversation.bot_mode = bool(bot_on)
        conversation.handoff_required = not bool(bot_on)
        if not bot_on:
            conversation.status = "needs_reply"
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def get_conversation_bot_mode(identifier: str) -> bool:
    record = get_conversation_record(identifier)
    return True if record is None else bool(record.get("bot_mode", True))


def mark_conversation_handoff_required(identifier: str, required: bool = True) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        conversation.handoff_required = bool(required)
        if required:
            conversation.bot_mode = False
            conversation.status = "needs_reply"
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def set_conversation_status(identifier: str, status: str) -> dict:
    initialize_storage()
    if status not in CONVERSATION_STATUSES:
        raise ValueError(f"Invalid conversation status '{status}'. Must be one of: {CONVERSATION_STATUSES}")
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        conversation.status = status
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def assign_conversation(identifier: str, user_id: Optional[str]) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        if user_id:
            user = session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user is None:
                raise ValueError("Assigned user not found")
            membership = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == conversation.workspace_id,
                    WorkspaceMembership.user_id == user_id,
                    WorkspaceMembership.status == "active",
                )
            ).scalar_one_or_none()
            if membership is None:
                raise ValueError("Assigned user is not an active member of this workspace")
        conversation.assigned_user_id = user_id
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def set_conversation_use_case(
    identifier: str,
    use_case_key: str,
    source_type: Optional[str] = None,
    source_ref: Optional[str] = None,
    active_reply_policy_key: Optional[str] = None,
    human_queue: Optional[str] = None,
) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        conversation.use_case_key = (use_case_key or "default_inbound").strip() or "default_inbound"
        if source_type is not None:
            conversation.source_type = (source_type or "direct_inbound").strip() or "direct_inbound"
        if source_ref is not None:
            conversation.source_ref = (source_ref or "").strip() or None
        conversation.active_reply_policy_key = (
            (active_reply_policy_key or conversation.use_case_key).strip() or conversation.use_case_key
        )
        if human_queue is not None:
            conversation.human_queue = (human_queue or "").strip() or None
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def set_conversation_ai_assist(identifier: str, draft: Optional[str], status: Optional[str] = None) -> dict:
    initialize_storage()
    with session_scope() as session:
        conversation = _resolve_conversation(session, identifier)
        if conversation is None:
            raise FileNotFoundError(f"Conversation or contact {identifier} not found")
        contact = _conversation_contact(session, conversation)
        conversation.ai_assist_draft = (draft or "").strip() or None
        conversation.ai_assist_status = status or ("available" if conversation.ai_assist_draft else None)
        conversation.ai_assist_updated_at = _now() if conversation.ai_assist_draft else None
        conversation.updated_at = _now()
        session.flush()
        return _serialize_conversation(conversation, contact)


def update_message_status_by_wa_id(wa_message_id: str, status: str, recipient: Optional[str] = None) -> bool:
    initialize_storage()
    with session_scope() as session:
        message = session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.wa_message_id == wa_message_id)
            .order_by(ConversationMessage.id.desc())
        ).scalars().first()
        if message is None:
            return False
        message.delivery_status = status
        conversation = _conversation_by_id(session, message.conversation_id)
        if conversation is None:
            return False
        session.add(
            MessageStatusEvent(
                workspace_id=message.workspace_id,
                conversation_id=conversation.id,
                wa_message_id=wa_message_id,
                status=status,
                recipient=recipient,
            )
        )
        conversation.updated_at = _now()
        return True


def get_conversation_metrics() -> dict:
    initialize_storage()
    with session_scope() as session:
        workspace_id = _workspace_id(session)
        conversations = session.execute(
            select(Conversation).where(Conversation.workspace_id == workspace_id)
        ).scalars().all()
        status_counts = {status: 0 for status in CONVERSATION_STATUSES}
        response_seconds = []
        for conversation in conversations:
            if conversation.status in status_counts:
                status_counts[conversation.status] += 1
            if conversation.last_inbound_at and conversation.last_outbound_at and conversation.last_outbound_at >= conversation.last_inbound_at:
                response_seconds.append((conversation.last_outbound_at - conversation.last_inbound_at).total_seconds())

        delivered = session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.workspace_id == workspace_id,
                ConversationMessage.delivery_status == "delivered",
            )
        ).scalar_one()
        read = session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.workspace_id == workspace_id,
                ConversationMessage.delivery_status == "read",
            )
        ).scalar_one()
        sent = session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.workspace_id == workspace_id,
                ConversationMessage.direction == "outbound",
            )
        ).scalar_one()

        return {
            "total_conversations": len(conversations),
            "unassigned_conversations": len([c for c in conversations if c.assigned_user_id is None]),
            "handoff_required": len([c for c in conversations if c.handoff_required]),
            "needs_reply": status_counts["needs_reply"],
            "status_counts": status_counts,
            "avg_response_seconds": (sum(response_seconds) / len(response_seconds)) if response_seconds else 0,
            "sent_messages": int(sent or 0),
            "delivered_messages": int(delivered or 0),
            "read_messages": int(read or 0),
        }


def import_contacts_csv(csv_content: str) -> dict:
    initialize_storage()
    result = {"created": 0, "skipped": 0, "errors": []}
    reader = csv.DictReader(io.StringIO(csv_content))
    required_headers = {"name", "phone"}
    if not reader.fieldnames:
        result["errors"].append("CSV has no headers")
        return result

    headers = {header.strip().lower() for header in reader.fieldnames}
    missing = required_headers - headers
    if missing:
        result["errors"].append(f"Missing required CSV headers: {missing}")
        return result

    for row_num, row in enumerate(reader, start=2):
        row = {key.strip().lower(): value.strip() if value else "" for key, value in row.items()}
        name = row.get("name", "")
        phone = normalize_phone(row.get("phone", ""))
        if not name or not phone:
            result["errors"].append(f"Row {row_num}: missing name or phone")
            continue
        if contact_exists(phone):
            result["skipped"] += 1
            continue

        tags = [tag.strip() for tag in row.get("tags", "").split(";") if tag.strip()]
        try:
            create_contact(
                name=name,
                phone=phone,
                company=row.get("company") or None,
                source=row.get("source") or None,
                tags=tags,
            )
            result["created"] += 1
        except Exception as exc:
            result["errors"].append(f"Row {row_num} ({name}): {exc}")

    logger.info(
        f"CSV import complete: {result['created']} created, "
        f"{result['skipped']} skipped, {len(result['errors'])} errors"
    )
    return result
