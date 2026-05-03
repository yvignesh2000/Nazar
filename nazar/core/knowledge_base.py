"""
Nazar — Structured Knowledge Base with RAG

Replaces the single flat knowledge_base.txt with a multi-document system
that uses ChromaDB for semantic retrieval. Only relevant chunks are injected
into the AI system prompt — preventing token bloat and improving response quality.

Features
--------
- Multiple KB documents (text, markdown, PDF extract, CSV, HTML)
- Folders for organizing documents
- Automatic chunking (512-word windows, 50-word overlap)
- ChromaDB vector storage per scope (global / per-campaign)
- Query-time RAG: retrieve top-k chunks matching the customer's message
- Graceful fallback to full-text when ChromaDB is unavailable
- Backward-compatible: existing knowledge_base.txt is auto-imported on first use

Document scopes
---------------
global         Shared across all conversations (default KB)
campaign       Specific to one campaign (overrides global for that campaign)

Storage layout::

    data/kb/
        docs.json              # Document metadata index (docs + folders)
        global/                # ChromaDB collection for global KB
        campaign_{id}/         # ChromaDB collection for campaign KB
    data/knowledge_base.txt    # Legacy flat file (kept as fallback)
    data/campaign_kb/          # Legacy per-campaign text files (kept as fallback)
"""

import json
import logging
import uuid
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"
KB_DIR = DATA_DIR / "kb"

# Patch sqlite3 with pysqlite3 for ChromaDB compatibility on Python 3.8
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = False
    logger.info("ChromaDB not available — KB will use full-text fallback")


# ──────────────────────────────────────────────────────────────────────────────
# ChromaDB client (lazy init)
# ──────────────────────────────────────────────────────────────────────────────

_chroma_client = None


def _get_chroma():
    global _chroma_client
    if not CHROMADB_AVAILABLE:
        return None
    if _chroma_client is None:
        try:
            KB_DIR.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(KB_DIR / "vectors"))
        except Exception as e:
            logger.warning("ChromaDB init failed: %s", e)
            return None
    return _chroma_client


def _collection_name(scope, campaign_id=None):
    # type: (str, Optional[str]) -> str
    if scope == "global":
        return "kb_global"
    return "kb_campaign_%s" % campaign_id


# ──────────────────────────────────────────────────────────────────────────────
# Document metadata index
# ──────────────────────────────────────────────────────────────────────────────

def _docs_path():
    # type: () -> Path
    KB_DIR.mkdir(parents=True, exist_ok=True)
    return KB_DIR / "docs.json"


def _load_docs():
    # type: () -> dict
    path = _docs_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_docs(data):
    # type: (dict) -> None
    path = _docs_path()
    lock = path.with_suffix(".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Text chunking
# ──────────────────────────────────────────────────────────────────────────────

def chunk_text(text, chunk_size=512, overlap=50):
    # type: (str, int, int) -> List[str]
    """
    Split ``text`` into overlapping word-based chunks.

    Args:
        text:       Input text.
        chunk_size: Target words per chunk.
        overlap:    Words shared between consecutive chunks.

    Returns:
        List of chunk strings.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i: i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)

    return chunks or [text[:4000]]  # at minimum return the whole text


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def add_document(
    title,          # type: str
    content,        # type: str
    doc_type="text",   # type: str
    scope="global",    # type: str
    campaign_id=None,  # type: Optional[str]
    folder_id=None,    # type: Optional[str]
):
    # type: (...) -> dict
    """
    Add a document to the knowledge base and index its chunks.

    Args:
        title:       Human-readable document title.
        content:     Full document text.
        doc_type:    "text" | "markdown" | "pdf" | "csv" | "html"
        scope:       "global" or "campaign"
        campaign_id: Required when scope == "campaign".
        folder_id:   Optional folder to place the document in.

    Returns:
        Document metadata record.
    """
    # Validate folder exists if specified
    if folder_id:
        folders = _load_folders()
        if folder_id not in folders:
            raise ValueError("Folder not found: %s" % folder_id)

    doc_id = "doc_%s" % uuid.uuid4().hex[:10]
    chunks = chunk_text(content)

    # Index in ChromaDB
    client = _get_chroma()
    if client:
        try:
            col_name = _collection_name(scope, campaign_id)
            collection = client.get_or_create_collection(
                col_name,
                metadata={"hnsw:space": "cosine"},
            )
            collection.add(
                ids=["%s_c%d" % (doc_id, i) for i in range(len(chunks))],
                documents=chunks,
                metadatas=[
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "chunk_index": i,
                        "scope": scope,
                        "campaign_id": campaign_id or "",
                        # Empty string sentinel (ChromaDB metadata values must be primitives,
                        # and None is treated inconsistently across versions).
                        "folder_id": folder_id or "",
                    }
                    for i in range(len(chunks))
                ],
            )
        except Exception as e:
            logger.warning("KB ChromaDB indexing failed: %s", e)

    # Save document metadata
    doc_meta = {
        "id": doc_id,
        "title": title,
        "type": doc_type,
        "scope": scope,
        "campaign_id": campaign_id or "",
        "folder_id": folder_id or None,
        "chunk_count": len(chunks),
        "char_count": len(content),
        "created_at": datetime.now(IST).isoformat(),
    }
    docs = _load_docs()
    docs[doc_id] = doc_meta
    _save_docs(docs)

    # Also persist raw text (for fallback)
    _save_raw_text(doc_id, content, scope, campaign_id)

    logger.info("KB document added: %r (%d chunks, scope=%s)", title, len(chunks), scope)
    return doc_meta


def query(
    question,            # type: str
    scope="global",      # type: str
    campaign_id=None,    # type: Optional[str]
    n_results=5,         # type: int
    folder_ids=None,     # type: Optional[List[str]]
    include_root=True,   # type: bool
):
    # type: (...) -> str
    """
    Retrieve the most relevant KB chunks for ``question``.

    Args:
        question:     Natural-language query.
        scope:        "global" or "campaign".
        campaign_id:  Required when scope == "campaign".
        n_results:    Max chunks to return.
        folder_ids:   Optional list of folder IDs to restrict retrieval to.
                      None or empty list = no folder filter (search everything).
        include_root: When folder_ids is set, also include unfiled (root) docs.

    Returns:
        Concatenated relevant text ready to inject into the system prompt.
        Falls back to full-text legacy files if ChromaDB is unavailable.
    """
    if not question or not isinstance(question, str):
        return ""

    client = _get_chroma()
    if client:
        try:
            col_name = _collection_name(scope, campaign_id)
            collection = client.get_collection(col_name)
            count = collection.count()
            if count == 0:
                return _fallback_text(scope, campaign_id, question=question)

            # Build optional metadata filter for folder scoping.
            where = None
            if folder_ids:
                allowed = list({fid for fid in folder_ids if fid})
                if include_root:
                    allowed.append("")  # root sentinel
                if allowed:
                    where = {"folder_id": {"$in": allowed}} if len(allowed) > 1 \
                        else {"folder_id": allowed[0]}

            query_kwargs = {
                "query_texts": [question],
                "n_results": min(n_results, count),
            }
            if where is not None:
                query_kwargs["where"] = where

            results = collection.query(**query_kwargs)
            if results and results.get("documents") and results["documents"][0]:
                chunks = results["documents"][0]
                return "\n\n---\n\n".join(chunks)
        except Exception as e:
            logger.debug("KB query failed, using fallback: %s", e)

    # Fallback: keyword-ranked concatenation of all sources
    return _fallback_text(scope, campaign_id, question=question)


def list_documents(scope=None, campaign_id=None, folder_id=None):
    # type: (Optional[str], Optional[str], Optional[str]) -> List[dict]
    """
    List all documents, optionally filtered by scope, campaign, or folder.

    Args:
        scope:       Filter by scope ("global" or "campaign").
        campaign_id: Filter by campaign.
        folder_id:   Filter by folder. Use "" to get root-level (unfiled) docs.
                     Use a folder ID to get docs in that folder. None = all docs.
    """
    docs = list(_load_docs().values())
    if scope:
        docs = [d for d in docs if d.get("scope") == scope]
    if campaign_id:
        docs = [d for d in docs if d.get("campaign_id") == campaign_id]
    if folder_id is not None:
        if folder_id == "":
            # Root-level: docs with no folder_id
            docs = [d for d in docs if not d.get("folder_id")]
        else:
            docs = [d for d in docs if d.get("folder_id") == folder_id]
    return sorted(docs, key=lambda d: d.get("created_at", ""), reverse=True)


def delete_document(doc_id):
    # type: (str) -> bool
    """Delete a document and its vector chunks."""
    docs = _load_docs()
    doc = docs.get(doc_id)
    if not doc:
        return False

    # Remove from ChromaDB
    client = _get_chroma()
    if client:
        try:
            col_name = _collection_name(doc["scope"], doc.get("campaign_id") or None)
            collection = client.get_collection(col_name)
            # Delete all chunks for this doc
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception as e:
            logger.warning("KB ChromaDB delete failed: %s", e)

    # Remove raw text
    raw_path = _raw_text_path(doc_id)
    if raw_path.exists():
        try:
            raw_path.unlink()
        except Exception:
            pass

    del docs[doc_id]
    _save_docs(docs)
    return True


def get_document(doc_id):
    # type: (str) -> Optional[dict]
    return _load_docs().get(doc_id)


# ──────────────────────────────────────────────────────────────────────────────
# Folder management
# ──────────────────────────────────────────────────────────────────────────────

def _folders_path():
    # type: () -> Path
    KB_DIR.mkdir(parents=True, exist_ok=True)
    return KB_DIR / "folders.json"


def _load_folders():
    # type: () -> dict
    path = _folders_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_folders(data):
    # type: (dict) -> None
    path = _folders_path()
    lock = path.with_suffix(".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def create_folder(name, parent_id=None):
    # type: (str, Optional[str]) -> dict
    """
    Create a new folder in the knowledge base.

    Args:
        name:      Folder name.
        parent_id: Optional parent folder ID for nesting.

    Returns:
        Folder metadata record.
    """
    folders = _load_folders()

    # Validate parent exists if specified
    if parent_id and parent_id not in folders:
        raise ValueError("Parent folder not found")

    folder_id = "fld_%s" % uuid.uuid4().hex[:10]
    folder = {
        "id": folder_id,
        "name": name.strip(),
        "parent_id": parent_id or None,
        "created_at": datetime.now(IST).isoformat(),
        "updated_at": datetime.now(IST).isoformat(),
    }
    folders[folder_id] = folder
    _save_folders(folders)
    logger.info("KB folder created: %r (id=%s, parent=%s)", name, folder_id, parent_id)
    return folder


def list_folders(parent_id=None):
    # type: (Optional[str]) -> List[dict]
    """
    List folders, optionally filtered by parent folder.

    Args:
        parent_id: If provided, returns only children of this folder.
                   If None, returns all folders.

    Returns:
        List of folder metadata records.
    """
    folders = list(_load_folders().values())
    if parent_id is not None:
        # parent_id="" means root-level folders (no parent)
        target = None if parent_id == "" else parent_id
        folders = [f for f in folders if f.get("parent_id") == target]
    return sorted(folders, key=lambda f: f.get("name", "").lower())


def get_folder(folder_id):
    # type: (str) -> Optional[dict]
    return _load_folders().get(folder_id)


def rename_folder(folder_id, new_name):
    # type: (str, str) -> Optional[dict]
    """Rename a folder. Returns updated folder or None if not found."""
    folders = _load_folders()
    folder = folders.get(folder_id)
    if not folder:
        return None
    folder["name"] = new_name.strip()
    folder["updated_at"] = datetime.now(IST).isoformat()
    _save_folders(folders)
    logger.info("KB folder renamed: %s -> %r", folder_id, new_name)
    return folder


def delete_folder(folder_id, recursive=False):
    # type: (str, bool) -> bool
    """
    Delete a folder.

    Args:
        folder_id: Folder to delete.
        recursive: If True, also deletes all documents and subfolders inside.
                   If False, moves contents to root (folder_id=None) before deleting.

    Returns:
        True if deleted, False if folder not found.
    """
    folders = _load_folders()
    if folder_id not in folders:
        return False

    if recursive:
        # Delete all documents in this folder
        docs = _load_docs()
        doc_ids_to_delete = [d["id"] for d in docs.values() if d.get("folder_id") == folder_id]
        for doc_id in doc_ids_to_delete:
            delete_document(doc_id)

        # Recursively delete child folders
        child_ids = [f["id"] for f in folders.values() if f.get("parent_id") == folder_id]
        for child_id in child_ids:
            delete_folder(child_id, recursive=True)
        # Reload folders since recursive calls may have changed them
        folders = _load_folders()
    else:
        # Move all documents in this folder to root
        docs = _load_docs()
        changed = False
        for doc in docs.values():
            if doc.get("folder_id") == folder_id:
                doc["folder_id"] = None
                changed = True
        if changed:
            _save_docs(docs)

        # Move child folders to root
        changed_folders = False
        for f in folders.values():
            if f.get("parent_id") == folder_id:
                f["parent_id"] = None
                changed_folders = True

    del folders[folder_id]
    _save_folders(folders)
    logger.info("KB folder deleted: %s (recursive=%s)", folder_id, recursive)
    return True


def move_document(doc_id, folder_id):
    # type: (str, Optional[str]) -> Optional[dict]
    """
    Move a document into a folder (or to root if folder_id is None).

    Returns:
        Updated document metadata, or None if doc not found.
    """
    docs = _load_docs()
    doc = docs.get(doc_id)
    if not doc:
        return None

    # Validate folder exists if specified
    if folder_id:
        folders = _load_folders()
        if folder_id not in folders:
            raise ValueError("Folder not found")

    doc["folder_id"] = folder_id
    _save_docs(docs)
    logger.info("KB document %s moved to folder %s", doc_id, folder_id)
    return doc


def get_folder_doc_counts():
    # type: () -> Dict[str, int]
    """Return a dict mapping folder_id -> number of documents in that folder."""
    docs = _load_docs()
    counts = {}  # type: Dict[str, int]
    for d in docs.values():
        fid = d.get("folder_id") or "__root__"
        counts[fid] = counts.get(fid, 0) + 1
    return counts


def import_legacy_kb():
    # type: () -> Optional[dict]
    """
    One-time import of existing knowledge_base.txt into the structured KB.
    Returns the created doc record, or None if already imported or file missing.
    """
    legacy_path = DATA_DIR / "knowledge_base.txt"
    if not legacy_path.exists():
        return None

    # Check if already imported
    docs = _load_docs()
    for d in docs.values():
        if d.get("title") == "__legacy_global_kb__":
            return None  # Already imported

    content = legacy_path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    return add_document(
        title="__legacy_global_kb__",
        content=content,
        doc_type="text",
        scope="global",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _raw_text_dir():
    # type: () -> Path
    d = KB_DIR / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _raw_text_path(doc_id):
    # type: (str) -> Path
    return _raw_text_dir() / ("%s.txt" % doc_id)


def _save_raw_text(doc_id, content, scope, campaign_id):
    # type: (str, str, str, Optional[str]) -> None
    _raw_text_path(doc_id).write_text(content, encoding="utf-8")


def _keyword_score(text, query_words):
    # type: (str, list) -> int
    """Simple keyword relevance score: count how many query words appear in text."""
    text_lower = text.lower()
    return sum(1 for w in query_words if w in text_lower)


def _fallback_text(scope, campaign_id, question=""):
    # type: (str, Optional[str], str) -> str
    """Return raw text from all KB sources when ChromaDB is unavailable.

    Merges structured documents (uploaded files + text docs) AND the legacy
    ``knowledge_base.txt`` into a single context block.  When a ``question``
    is provided, documents are ranked by simple keyword overlap so the most
    relevant content appears first (poor-man's retrieval).

    Concatenation is capped at 8000 characters to keep prompt size manageable.
    """
    MAX_CHARS = 8000
    segments = []  # list of (text, source_label)

    # ── 1. Structured documents (raw text files) ────────────────
    docs = _load_docs()
    for d in docs.values():
        if d.get("scope") == scope and (
            scope == "global" or d.get("campaign_id") == campaign_id
        ):
            raw = _raw_text_path(d["id"])
            if raw.exists():
                text = raw.read_text(encoding="utf-8").strip()
                if text:
                    segments.append((text, d.get("title", d["id"])))

    # ── 2. Legacy flat files (always included for global scope) ─
    if scope == "global":
        legacy_path = DATA_DIR / "knowledge_base.txt"
        if legacy_path.exists():
            legacy_text = legacy_path.read_text(encoding="utf-8").strip()
            if legacy_text:
                # Avoid duplicating if the legacy file was already imported
                already_imported = any(
                    d.get("title") == "__legacy_global_kb__" for d in docs.values()
                )
                if not already_imported:
                    segments.append((legacy_text, "knowledge_base.txt"))
    elif scope == "campaign":
        campaign_path = DATA_DIR / "campaign_kb" / ("%s.txt" % campaign_id)
        if campaign_path and campaign_path.exists():
            campaign_text = campaign_path.read_text(encoding="utf-8").strip()
            if campaign_text:
                segments.append((campaign_text, "campaign_kb"))

    if not segments:
        return ""

    # ── 3. Keyword-rank segments when a question is provided ────
    if question:
        query_words = [w.lower() for w in question.split() if len(w) > 2]
        if query_words:
            segments.sort(key=lambda s: _keyword_score(s[0], query_words), reverse=True)

    # ── 4. Concatenate up to MAX_CHARS ──────────────────────────
    parts = []
    total = 0
    for text, _label in segments:
        remaining = MAX_CHARS - total
        if remaining <= 0:
            break
        chunk = text[:remaining]
        parts.append(chunk)
        total += len(chunk)

    return "\n\n---\n\n".join(parts)
