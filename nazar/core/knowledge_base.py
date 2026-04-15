"""
Nazar — Structured Knowledge Base with RAG

Replaces the single flat knowledge_base.txt with a multi-document system
that uses ChromaDB for semantic retrieval. Only relevant chunks are injected
into the AI system prompt — preventing token bloat and improving response quality.

Features
--------
- Multiple KB documents (text, markdown, PDF extract, CSV)
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
        docs.json              # Document metadata index
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
):
    # type: (...) -> dict
    """
    Add a document to the knowledge base and index its chunks.

    Args:
        title:       Human-readable document title.
        content:     Full document text.
        doc_type:    "text" | "markdown" | "pdf" | "csv"
        scope:       "global" or "campaign"
        campaign_id: Required when scope == "campaign".

    Returns:
        Document metadata record.
    """
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
    question,        # type: str
    scope="global",  # type: str
    campaign_id=None,  # type: Optional[str]
    n_results=5,       # type: int
):
    # type: (...) -> str
    """
    Retrieve the most relevant KB chunks for ``question``.

    Returns:
        Concatenated relevant text ready to inject into the system prompt.
        Falls back to full-text legacy files if ChromaDB is unavailable.
    """
    client = _get_chroma()
    if client:
        try:
            col_name = _collection_name(scope, campaign_id)
            collection = client.get_collection(col_name)
            results = collection.query(
                query_texts=[question],
                n_results=min(n_results, collection.count()),
            )
            if results and results["documents"] and results["documents"][0]:
                chunks = results["documents"][0]
                return "\n\n---\n\n".join(chunks)
        except Exception as e:
            logger.debug("KB query failed, using fallback: %s", e)

    # Fallback: legacy flat files
    return _fallback_text(scope, campaign_id)


def list_documents(scope=None, campaign_id=None):
    # type: (Optional[str], Optional[str]) -> List[dict]
    """List all documents, optionally filtered by scope / campaign."""
    docs = list(_load_docs().values())
    if scope:
        docs = [d for d in docs if d.get("scope") == scope]
    if campaign_id:
        docs = [d for d in docs if d.get("campaign_id") == campaign_id]
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


def _fallback_text(scope, campaign_id):
    # type: (str, Optional[str]) -> str
    """Return raw text from legacy files when ChromaDB is unavailable."""
    # Try raw stored chunks first
    docs = _load_docs()
    for d in docs.values():
        if d.get("scope") == scope and (
            scope == "global" or d.get("campaign_id") == campaign_id
        ):
            raw = _raw_text_path(d["id"])
            if raw.exists():
                return raw.read_text(encoding="utf-8")[:4000]

    # Fall back to legacy flat files
    if scope == "global":
        path = DATA_DIR / "knowledge_base.txt"
    else:
        path = DATA_DIR / "campaign_kb" / ("%s.txt" % campaign_id)

    if path and path.exists():
        return path.read_text(encoding="utf-8")[:4000]

    return ""
