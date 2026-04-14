"""
Campaign-scoped knowledge packs.

Each campaign can carry its own notes, operator instructions, and uploaded
reference files so replies can use campaign-specific context instead of
falling back only to the global business knowledge base.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from workspace_store import get_workspace_config, update_workspace_config

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ASSET_ROOT = DATA_DIR / "campaign_knowledge"


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _index() -> dict:
    config = get_workspace_config()
    raw = config.get("campaign_knowledge") or {}
    return raw if isinstance(raw, dict) else {}


def _write_index(index: dict) -> None:
    update_workspace_config({"campaign_knowledge": index})


def _campaign_entry(campaign_key: str) -> dict:
    return dict((_index().get(campaign_key) or {}))


def _campaign_dir(campaign_key: str) -> Path:
    path = ASSET_ROOT / campaign_key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _text_from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""
    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages[:12]:
            chunks.append((page.extract_text() or "").strip())
        return "\n\n".join(chunk for chunk in chunks if chunk)
    except Exception as exc:
        logger.warning("Failed to extract PDF text from %s: %s", path.name, exc)
        return ""


def _text_from_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.warning("Failed to extract DOCX text from %s: %s", path.name, exc)
        return ""
    text = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_text(path: Path, mime_type: str = "") -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".html", ".htm"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf" or mime_type == "application/pdf":
        return _text_from_pdf(path)
    if suffix == ".docx" or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _text_from_docx(path)
    return ""


def _persist_uploaded_file(campaign_key: str, filename: str, source_path: Path, mime_type: str = "") -> dict:
    safe_name = Path(filename or source_path.name).name or "campaign_file"
    file_id = str(uuid4())
    campaign_dir = _campaign_dir(campaign_key)
    stored_name = f"{file_id}_{safe_name}"
    stored_path = campaign_dir / stored_name
    shutil.copy2(source_path, stored_path)
    extracted_text = (_extract_text(stored_path, mime_type) or "").strip()
    text_path = campaign_dir / f"{file_id}.txt"
    text_path.write_text(extracted_text, encoding="utf-8")
    return {
        "id": file_id,
        "name": safe_name,
        "mime_type": mime_type or "",
        "stored_path": str(stored_path.relative_to(DATA_DIR)),
        "text_path": str(text_path.relative_to(DATA_DIR)),
        "text_chars": len(extracted_text),
        "uploaded_at": _now_iso(),
    }


def get_campaign_knowledge(campaign_key: str) -> dict:
    entry = _campaign_entry(campaign_key)
    return {
        "campaign_key": campaign_key,
        "notes": entry.get("notes", "") or "",
        "instruction": entry.get("instruction", "") or "",
        "files": entry.get("files", []) or [],
        "updated_at": entry.get("updated_at"),
    }


def save_campaign_knowledge(campaign_key: str, *, notes: Optional[str] = None, instruction: Optional[str] = None) -> dict:
    index = _index()
    entry = dict(index.get(campaign_key) or {})
    if notes is not None:
        entry["notes"] = notes.strip()
    if instruction is not None:
        entry["instruction"] = instruction.strip()
    entry["files"] = entry.get("files", []) or []
    entry["updated_at"] = _now_iso()
    index[campaign_key] = entry
    _write_index(index)
    return get_campaign_knowledge(campaign_key)


def add_campaign_file(campaign_key: str, *, filename: str, source_path: Path, mime_type: str = "") -> dict:
    uploaded = _persist_uploaded_file(campaign_key, filename, source_path, mime_type)
    index = _index()
    entry = dict(index.get(campaign_key) or {})
    files = list(entry.get("files", []) or [])
    files.append(uploaded)
    entry["files"] = files
    entry["notes"] = entry.get("notes", "") or ""
    entry["instruction"] = entry.get("instruction", "") or ""
    entry["updated_at"] = _now_iso()
    index[campaign_key] = entry
    _write_index(index)
    return uploaded


def delete_campaign_file(campaign_key: str, file_id: str) -> dict:
    index = _index()
    entry = dict(index.get(campaign_key) or {})
    files = list(entry.get("files", []) or [])
    removed = next((item for item in files if item.get("id") == file_id), None)
    if not removed:
        raise ValueError("Campaign file not found")
    remaining = [item for item in files if item.get("id") != file_id]
    for rel_key in ("stored_path", "text_path"):
        rel = removed.get(rel_key)
        if rel:
            try:
                (DATA_DIR / rel).unlink(missing_ok=True)
            except Exception:
                pass
    entry["files"] = remaining
    entry["updated_at"] = _now_iso()
    index[campaign_key] = entry
    _write_index(index)
    return {"deleted": True, "file_id": file_id}


def campaign_knowledge_summary(campaign_key: str) -> dict:
    data = get_campaign_knowledge(campaign_key)
    return {
        "campaign_key": campaign_key,
        "has_notes": bool(data["notes"].strip()),
        "has_instruction": bool(data["instruction"].strip()),
        "file_count": len(data["files"]),
        "updated_at": data.get("updated_at"),
    }


def build_campaign_context(campaign_key: Optional[str]) -> str:
    key = (campaign_key or "").strip()
    if not key:
        return ""
    data = get_campaign_knowledge(key)
    sections: list[str] = []
    if data["notes"].strip():
        sections.append(f"## Campaign Notes\n{data['notes'].strip()}")
    if data["instruction"].strip():
        sections.append(f"## Campaign Reply Instructions\n{data['instruction'].strip()}")
    file_sections = []
    total_chars = 0
    for item in data["files"]:
        rel = item.get("text_path")
        if not rel:
            continue
        try:
            extracted = (DATA_DIR / rel).read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            extracted = ""
        if not extracted:
            continue
        remaining = 5000 - total_chars
        if remaining <= 0:
            break
        snippet = extracted[:remaining]
        total_chars += len(snippet)
        file_sections.append(f"### {item.get('name') or 'Attachment'}\n{snippet}")
    if file_sections:
        sections.append("## Campaign Attachments\n" + "\n\n".join(file_sections))
    return "\n\n".join(sections).strip()
