"""
Nazar — Contact Manager (CRM Data Layer)

Handles contact creation, pipeline management, lead scoring,
conversation logging, and CSV import for the WhatsApp Sales
Intelligence Platform.

All contact data is encrypted at rest using per-contact keys
derived from the contact's phone number (same HKDF pattern
as Nazar user_manager).

Storage layout:
  data/contacts/{contact_id}/
    profile.json.enc          — contact details (encrypted)
    conversations/
      YYYY-MM-DD.jsonl.enc    — daily conversation logs (encrypted)
"""

import csv
import fcntl
import io
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from encryption import encrypt_json, decrypt_json, encrypt_file, decrypt_file

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "contacts"

PIPELINE_STAGES = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]


# ---------------------------------------------------------------------------
# Phone number normalization
# ---------------------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """
    Normalize a phone number to E.164 format.

    - Strip spaces, dashes, parentheses, dots
    - If starts with digits (no +), prepend +
    - Result looks like +919876543210
    """
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone)
    if cleaned and cleaned[0] != "+" and cleaned[0].isdigit():
        cleaned = "+" + cleaned
    return cleaned


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _contact_dir(contact_id: str) -> Path:
    """Get the directory for a specific contact."""
    return DATA_DIR / contact_id


def _profile_path(contact_id: str) -> Path:
    """Get the encrypted profile path for a contact."""
    return _contact_dir(contact_id) / "profile.json.enc"


def _conversations_dir(contact_id: str) -> Path:
    """Get the conversations directory for a contact."""
    return _contact_dir(contact_id) / "conversations"


def _locked_write(filepath: Path, data_bytes: bytes):
    """Write bytes to a file with an exclusive file lock."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "wb") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(data_bytes)
        fcntl.flock(f, fcntl.LOCK_UN)


def _locked_read_append_write(phone: str, filepath: Path, new_content: str):
    """
    Read existing encrypted content, append new content, re-encrypt and write.
    Uses exclusive file lock to prevent race conditions on concurrent writes.
    """
    lock_path = filepath.with_suffix(filepath.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        existing = decrypt_file(phone, filepath) if filepath.exists() else ""
        encrypt_file(phone, filepath, existing + new_content)
        # Lock released when `with` exits


def _load_profile(contact_id: str) -> dict:
    """Load and decrypt a contact's profile. Raises FileNotFoundError if missing."""
    path = _profile_path(contact_id)
    if not path.exists():
        raise FileNotFoundError(f"Contact {contact_id} not found")
    profile = decrypt_json(_get_phone_for_contact(contact_id), path)
    return profile


def _save_profile(contact_id: str, profile: dict):
    """Encrypt and save a contact's profile with file locking."""
    path = _profile_path(contact_id)
    phone = profile["phone"]
    encrypted = json.dumps(profile, ensure_ascii=False, indent=2)
    from encryption import encrypt_data
    data_bytes = encrypt_data(phone, encrypted)
    _locked_write(path, data_bytes)


def _get_phone_for_contact(contact_id: str) -> str:
    """
    Retrieve the phone number for a contact from a lightweight index,
    or fall back to reading the profile.

    Since the phone is the encryption key material, we keep a small
    plaintext index file mapping contact_id -> phone for bootstrap.
    """
    index_path = DATA_DIR / ".phone_index.json"
    if index_path.exists():
        with open(index_path, "r") as f:
            index = json.load(f)
        if contact_id in index:
            return index[contact_id]

    # Fallback: should not normally reach here after create_contact
    raise FileNotFoundError(
        f"No phone index entry for contact {contact_id}. "
        "Contact may not exist or index is corrupted."
    )


def _update_phone_index(contact_id: str, phone: str):
    """Add or update a contact_id -> phone mapping in the plaintext index."""
    index_path = DATA_DIR / ".phone_index.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    lock_path = index_path.with_suffix(".lock")
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        index = {}
        if index_path.exists():
            with open(index_path, "r") as f:
                index = json.load(f)
        index[contact_id] = phone
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)


def _remove_phone_index(contact_id: str):
    """Remove a contact_id from the phone index."""
    index_path = DATA_DIR / ".phone_index.json"
    if not index_path.exists():
        return

    lock_path = index_path.with_suffix(".lock")
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        with open(index_path, "r") as f:
            index = json.load(f)
        index.pop(contact_id, None)
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)


def _load_phone_index() -> dict:
    """Load the entire phone index. Returns {contact_id: phone}."""
    index_path = DATA_DIR / ".phone_index.json"
    if not index_path.exists():
        return {}
    with open(index_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------

def create_contact(
    name: str,
    phone: str,
    company: Optional[str] = None,
    source: Optional[str] = None,
    assigned_to: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """
    Create a new contact with encrypted profile.

    Returns the full contact dict with generated contact_id.
    Raises ValueError if a contact with the same phone already exists.
    """
    phone = normalize_phone(phone)

    if contact_exists(phone):
        raise ValueError(f"Contact with phone {phone} already exists")

    contact_id = uuid.uuid4().hex[:12]
    now = datetime.now(IST).isoformat()

    # Create directory structure
    contact_dir = _contact_dir(contact_id)
    (contact_dir / "conversations").mkdir(parents=True, exist_ok=True)

    profile = {
        "contact_id": contact_id,
        "name": name,
        "phone": phone,
        "company": company,
        "pipeline_stage": "New",
        "deal_value": 0.0,
        "lead_score": 0,
        "assigned_to": assigned_to,
        "tags": tags or [],
        "source": source,
        "last_contacted_at": None,
        "last_replied_at": None,
        "total_messages": 0,
        "opt_in": False,
        "opt_in_date": None,
        "created_at": now,
        "notes": "",
    }

    # Save encrypted profile
    encrypt_json(phone, _profile_path(contact_id), profile)

    # Update the phone index
    _update_phone_index(contact_id, phone)

    logger.info(f"Created contact: {contact_id} ({name}, {phone})")
    return profile


def get_contact(contact_id: str) -> dict:
    """Load and decrypt a contact's profile."""
    return _load_profile(contact_id)


def update_contact(contact_id: str, **fields) -> dict:
    """
    Update one or more fields on a contact's profile.

    Returns the updated profile dict.
    Raises FileNotFoundError if contact does not exist.
    """
    profile = _load_profile(contact_id)

    # Normalize phone if it's being updated
    if "phone" in fields:
        fields["phone"] = normalize_phone(fields["phone"])
        _update_phone_index(contact_id, fields["phone"])

    # Validate pipeline_stage if provided
    if "pipeline_stage" in fields and fields["pipeline_stage"] not in PIPELINE_STAGES:
        raise ValueError(
            f"Invalid pipeline stage '{fields['pipeline_stage']}'. "
            f"Must be one of: {PIPELINE_STAGES}"
        )

    # Validate lead_score if provided
    if "lead_score" in fields:
        score = fields["lead_score"]
        if not isinstance(score, (int, float)) or score < 0 or score > 100:
            raise ValueError("lead_score must be between 0 and 100")

    profile.update(fields)
    _save_profile(contact_id, profile)

    logger.info(f"Updated contact {contact_id}: {list(fields.keys())}")
    return profile


def delete_contact(contact_id: str):
    """
    Permanently delete a contact and all their data.
    Removes the contact directory and the phone index entry.
    """
    contact_dir = _contact_dir(contact_id)
    if contact_dir.exists():
        shutil.rmtree(contact_dir)
    _remove_phone_index(contact_id)
    logger.info(f"Deleted contact: {contact_id}")


def list_contacts(
    stage: Optional[str] = None,
    assigned_to: Optional[str] = None,
    tag: Optional[str] = None,
) -> list:
    """
    List all contacts, optionally filtered by pipeline stage,
    assigned_to, or tag.

    Returns a list of contact profile dicts.
    """
    if not DATA_DIR.exists():
        return []

    index = _load_phone_index()
    results = []

    for contact_id, phone in index.items():
        profile_path = _profile_path(contact_id)
        if not profile_path.exists():
            continue
        try:
            profile = decrypt_json(phone, profile_path)
        except Exception as e:
            logger.warning(f"Failed to decrypt contact {contact_id}: {e}")
            continue

        # Apply filters
        if stage and profile.get("pipeline_stage") != stage:
            continue
        if assigned_to and profile.get("assigned_to") != assigned_to:
            continue
        if tag and tag not in profile.get("tags", []):
            continue

        results.append(profile)

    return results


def get_contact_by_phone(phone: str) -> Optional[dict]:
    """
    Look up a contact by phone number.
    Returns the contact profile dict, or None if not found.
    """
    phone = normalize_phone(phone)
    index = _load_phone_index()

    for contact_id, indexed_phone in index.items():
        if indexed_phone == phone:
            try:
                return _load_profile(contact_id)
            except Exception:
                return None
    return None


def contact_exists(phone: str) -> bool:
    """Check if a contact with the given phone number exists."""
    phone = normalize_phone(phone)
    index = _load_phone_index()
    return phone in index.values()


# ---------------------------------------------------------------------------
# Pipeline & scoring
# ---------------------------------------------------------------------------

def move_stage(contact_id: str, new_stage: str) -> dict:
    """
    Move a contact to a new pipeline stage.

    Raises ValueError if the stage is invalid.
    Returns the updated profile.
    """
    if new_stage not in PIPELINE_STAGES:
        raise ValueError(
            f"Invalid pipeline stage '{new_stage}'. "
            f"Must be one of: {PIPELINE_STAGES}"
        )
    profile = _load_profile(contact_id)
    old_stage = profile.get("pipeline_stage")
    profile["pipeline_stage"] = new_stage
    _save_profile(contact_id, profile)
    logger.info(f"Contact {contact_id} moved: {old_stage} -> {new_stage}")
    return profile


def update_lead_score(contact_id: str, score: int) -> dict:
    """
    Set the lead score for a contact (0-100).

    Raises ValueError if score is out of range.
    Returns the updated profile.
    """
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        raise ValueError("lead_score must be between 0 and 100")
    profile = _load_profile(contact_id)
    profile["lead_score"] = int(score)
    _save_profile(contact_id, profile)
    logger.info(f"Contact {contact_id} lead_score set to {score}")
    return profile


def add_tag(contact_id: str, tag: str) -> dict:
    """
    Add a tag to a contact. Skips if tag already present.
    Returns the updated profile.
    """
    profile = _load_profile(contact_id)
    tags = profile.get("tags", [])
    if tag not in tags:
        tags.append(tag)
        profile["tags"] = tags
        _save_profile(contact_id, profile)
        logger.info(f"Contact {contact_id} tag added: {tag}")
    return profile


def remove_tag(contact_id: str, tag: str) -> dict:
    """
    Remove a tag from a contact. Silently ignores if tag not present.
    Returns the updated profile.
    """
    profile = _load_profile(contact_id)
    tags = profile.get("tags", [])
    if tag in tags:
        tags.remove(tag)
        profile["tags"] = tags
        _save_profile(contact_id, profile)
        logger.info(f"Contact {contact_id} tag removed: {tag}")
    return profile


def get_pipeline_summary() -> dict:
    """
    Return a summary of the sales pipeline.

    Returns a dict keyed by stage name, each with:
      {"count": int, "total_value": float}
    """
    summary = {stage: {"count": 0, "total_value": 0.0} for stage in PIPELINE_STAGES}
    contacts = list_contacts()

    for contact in contacts:
        stage = contact.get("pipeline_stage", "New")
        if stage in summary:
            summary[stage]["count"] += 1
            summary[stage]["total_value"] += float(contact.get("deal_value", 0))

    return summary


# ---------------------------------------------------------------------------
# Conversation logging
# ---------------------------------------------------------------------------

def save_message(
    contact_id: str,
    direction: str,
    content: str,
    sent_by: str = "bot",
    wa_message_id: Optional[str] = None,
) -> dict:
    """
    Save a message to the contact's daily conversation log.

    Args:
        contact_id: The contact's unique ID.
        direction: "inbound" or "outbound".
        content: The message text.
        sent_by: Who sent it — "bot", "agent", or contact name for inbound.
        wa_message_id: Optional WhatsApp message ID for tracking.

    Returns the saved message dict.
    """
    profile = _load_profile(contact_id)
    phone = profile["phone"]
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    conv_dir = _conversations_dir(contact_id)
    conv_dir.mkdir(parents=True, exist_ok=True)
    conv_file = conv_dir / f"{today}.jsonl.enc"

    message = {
        "timestamp": now.isoformat(),
        "direction": direction,
        "content": content,
        "sent_by": sent_by,
        "wa_message_id": wa_message_id,
    }

    # Append to today's conversation file with file lock
    _locked_read_append_write(
        phone, conv_file,
        json.dumps(message, ensure_ascii=False) + "\n"
    )

    # Update profile stats
    try:
        profile["total_messages"] = profile.get("total_messages", 0) + 1
        if direction == "outbound":
            profile["last_contacted_at"] = now.isoformat()
        elif direction == "inbound":
            profile["last_replied_at"] = now.isoformat()
        _save_profile(contact_id, profile)
    except Exception as e:
        logger.error(f"Failed to update profile stats for contact {contact_id}: {e}")

    return message


def get_today_conversation(contact_id: str) -> list:
    """Get today's messages for a contact."""
    profile = _load_profile(contact_id)
    phone = profile["phone"]
    today = datetime.now(IST).strftime("%Y-%m-%d")
    conv_file = _conversations_dir(contact_id) / f"{today}.jsonl.enc"

    if not conv_file.exists():
        return []

    raw = decrypt_file(phone, conv_file)
    messages = []
    for line in raw.strip().split("\n"):
        if line.strip():
            messages.append(json.loads(line))
    return messages


def get_conversation_history(contact_id: str, days: int = 7) -> list:
    """
    Get conversation history for the last N days.
    Returns messages sorted by timestamp (oldest first).
    """
    profile = _load_profile(contact_id)
    phone = profile["phone"]
    conv_dir = _conversations_dir(contact_id)
    all_messages = []

    for i in range(days):
        date = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
        conv_file = conv_dir / f"{date}.jsonl.enc"
        if conv_file.exists():
            try:
                raw = decrypt_file(phone, conv_file)
                for line in raw.strip().split("\n"):
                    if line.strip():
                        all_messages.append(json.loads(line))
            except Exception as e:
                logger.warning(f"Failed to read conversation {date} for {contact_id}: {e}")

    return sorted(all_messages, key=lambda m: m["timestamp"])


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def import_contacts_csv(csv_content: str) -> dict:
    """
    Parse CSV content and create contacts in bulk.

    Expected CSV headers: name, phone, company, tags, source
    - 'tags' column should be semicolon-separated (e.g. "vip;enterprise")
    - Rows with duplicate phone numbers (already in system) are skipped.

    Returns:
        {"created": int, "skipped": int, "errors": list[str]}
    """
    result = {"created": 0, "skipped": 0, "errors": []}

    reader = csv.DictReader(io.StringIO(csv_content))

    # Validate headers
    required_headers = {"name", "phone"}
    if not reader.fieldnames:
        result["errors"].append("CSV has no headers")
        return result

    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = required_headers - headers
    if missing:
        result["errors"].append(f"Missing required CSV headers: {missing}")
        return result

    for row_num, row in enumerate(reader, start=2):
        # Normalize header keys (strip whitespace)
        row = {k.strip().lower(): v.strip() if v else "" for k, v in row.items()}

        name = row.get("name", "").strip()
        phone = row.get("phone", "").strip()

        if not name or not phone:
            result["errors"].append(f"Row {row_num}: missing name or phone")
            continue

        phone = normalize_phone(phone)

        if contact_exists(phone):
            result["skipped"] += 1
            continue

        try:
            tags_str = row.get("tags", "")
            tags = [t.strip() for t in tags_str.split(";") if t.strip()] if tags_str else []

            create_contact(
                name=name,
                phone=phone,
                company=row.get("company", "").strip() or None,
                source=row.get("source", "").strip() or None,
                tags=tags,
            )
            result["created"] += 1
        except Exception as e:
            result["errors"].append(f"Row {row_num} ({name}): {e}")

    logger.info(
        f"CSV import complete: {result['created']} created, "
        f"{result['skipped']} skipped, {len(result['errors'])} errors"
    )
    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    test_phone_1 = "+919876543210"
    test_phone_2 = "+919876543211"

    # Clean slate
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    # 1. Create contact
    c1 = create_contact("Raj Kumar", test_phone_1, company="Acme Corp", source="website", tags=["enterprise"])
    print(f"Created: {c1['contact_id']} - {c1['name']} ({c1['phone']})")
    assert c1["pipeline_stage"] == "New"
    assert c1["tags"] == ["enterprise"]

    # 2. Get contact
    fetched = get_contact(c1["contact_id"])
    assert fetched["name"] == "Raj Kumar"
    print(f"Fetched: {fetched['name']}")

    # 3. Update contact
    updated = update_contact(c1["contact_id"], deal_value=50000, notes="Hot lead from website")
    assert updated["deal_value"] == 50000
    print(f"Updated: deal_value={updated['deal_value']}")

    # 4. Move pipeline stage
    moved = move_stage(c1["contact_id"], "Qualified")
    assert moved["pipeline_stage"] == "Qualified"
    print(f"Pipeline: {moved['pipeline_stage']}")

    # 5. Lead score
    scored = update_lead_score(c1["contact_id"], 75)
    assert scored["lead_score"] == 75
    print(f"Lead score: {scored['lead_score']}")

    # 6. Tags
    tagged = add_tag(c1["contact_id"], "vip")
    assert "vip" in tagged["tags"]
    untagged = remove_tag(c1["contact_id"], "enterprise")
    assert "enterprise" not in untagged["tags"]
    print(f"Tags: {untagged['tags']}")

    # 7. Phone lookup
    by_phone = get_contact_by_phone("9876543210")
    assert by_phone is not None
    assert by_phone["contact_id"] == c1["contact_id"]
    print(f"Phone lookup: found {by_phone['name']}")

    # 8. contact_exists
    assert contact_exists(test_phone_1) is True
    assert contact_exists("+910000000000") is False
    print("contact_exists: OK")

    # 9. Save messages
    msg1 = save_message(c1["contact_id"], "outbound", "Hi Raj, following up on your demo request.", sent_by="bot")
    msg2 = save_message(c1["contact_id"], "inbound", "Yes, I'd like to schedule a call.", sent_by="Raj Kumar")
    print(f"Messages saved: {msg1['direction']}, {msg2['direction']}")

    # 10. Get today's conversation
    today_msgs = get_today_conversation(c1["contact_id"])
    assert len(today_msgs) == 2
    print(f"Today's messages: {len(today_msgs)}")

    # 11. Conversation history
    history = get_conversation_history(c1["contact_id"], days=7)
    assert len(history) == 2
    print(f"History (7 days): {len(history)} messages")

    # 12. Create second contact + list
    c2 = create_contact("Priya Sharma", test_phone_2, company="Beta Inc", tags=["sme"])
    move_stage(c2["contact_id"], "Proposal")
    update_contact(c2["contact_id"], deal_value=25000)

    all_contacts = list_contacts()
    assert len(all_contacts) == 2
    print(f"All contacts: {len(all_contacts)}")

    filtered = list_contacts(stage="Qualified")
    assert len(filtered) == 1
    assert filtered[0]["name"] == "Raj Kumar"
    print(f"Filtered (Qualified): {len(filtered)}")

    # 13. Pipeline summary
    summary = get_pipeline_summary()
    assert summary["Qualified"]["count"] == 1
    assert summary["Proposal"]["count"] == 1
    print(f"Pipeline summary: {json.dumps(summary, indent=2)}")

    # 14. CSV import
    csv_data = """name,phone,company,tags,source
Amit Patel,+919876543212,Gamma Ltd,hot;enterprise,referral
Raj Kumar,+919876543210,Acme Corp,enterprise,website
,+919876543213,,,,
Neha Gupta,+919876543214,Delta Co,sme,cold-call
"""
    import_result = import_contacts_csv(csv_data)
    assert import_result["created"] == 2  # Amit and Neha
    assert import_result["skipped"] == 1  # Raj (duplicate)
    assert len(import_result["errors"]) == 1  # empty name row
    print(f"CSV import: {import_result}")

    # 15. Duplicate phone check
    try:
        create_contact("Duplicate", test_phone_1)
        print("FAIL: should have raised ValueError")
        sys.exit(1)
    except ValueError:
        print("Duplicate phone rejected: OK")

    # 16. Invalid stage
    try:
        move_stage(c1["contact_id"], "InvalidStage")
        print("FAIL: should have raised ValueError")
        sys.exit(1)
    except ValueError:
        print("Invalid stage rejected: OK")

    # 17. Delete contact
    delete_contact(c2["contact_id"])
    assert not _contact_dir(c2["contact_id"]).exists()
    remaining = list_contacts()
    print(f"After delete: {len(remaining)} contacts remain")

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\nAll tests passed!")
