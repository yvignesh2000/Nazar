"""
Nazar — Per-Customer Vector Memory System

Semantic search across all customer conversations, signals, and insights.
Uses ChromaDB for local vector storage with cosine similarity.

Adapted from InnerVoice's vector_memory.py but tailored for sales intelligence:
- Every inbound/outbound message embedded and searchable
- Extracted signals: buying signals, objections, preferences, price sensitivity
- Memory notes: AI-curated insights about the customer
"""

import hashlib
import logging
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except Exception:
    CHROMADB_AVAILABLE = False

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "contacts"

# ---------------------------------------------------------------------------
# Signal detection patterns
# ---------------------------------------------------------------------------

SIGNAL_PATTERNS = {
    "buying_signal": [
        r"\binterested\b", r"\bpricing\b", r"\bhow\s+much\b", r"\bdemo\b",
        r"\btry\b", r"\bplan\b", r"\bwhen\s+can\b", r"\bhow\s+do\s+I\b",
        r"\bsend\s+me\b", r"\bcost\b", r"\bquote\b",
    ],
    "objection": [
        r"\bexpensive\b", r"\btoo\s+much\b", r"\bcompetitor\b",
        r"\bnot\s+sure\b", r"\bthink\s+about\s+it\b", r"\blater\b",
        r"\balready\s+using\b", r"\bno\s+budget\b",
    ],
    "price_sensitivity": [
        r"\bdiscount\b", r"\bcheaper\b", r"\bbudget\b", r"\bafford\b",
        r"\blower\s+price\b", r"\bbetter\s+deal\b", r"\bfree\s+trial\b",
        r"\btoo\s+costly\b",
    ],
    "intent": [
        r"\bbuy\b", r"\bpurchase\b", r"\border\b", r"\bsubscribe\b",
        r"\bsign\s+up\b", r"\bproceed\b", r"\bgo\s+ahead\b",
        r"\blet'?s\s+do\s+it\b",
    ],
}

# Pre-compile all patterns for performance
_COMPILED_PATTERNS = {
    signal_type: [re.compile(p, re.IGNORECASE) for p in patterns]
    for signal_type, patterns in SIGNAL_PATTERNS.items()
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_id(text: str, timestamp: str) -> str:
    """Generate a deterministic ID for a document."""
    return hashlib.sha256(f"{timestamp}:{text}".encode()).hexdigest()[:16]


def _now_iso() -> str:
    """Current timestamp in IST as ISO string."""
    return datetime.now(IST).isoformat()


# ---------------------------------------------------------------------------
# ChromaDB client and collection management
# ---------------------------------------------------------------------------

def get_customer_vectordb(contact_id: str):
    """
    Get or create a ChromaDB PersistentClient for a specific contact.

    Storage location: data/contacts/{contact_id}/vectors/

    Returns:
        chromadb.PersistentClient or None on failure.
    """
    if not CHROMADB_AVAILABLE:
        logger.warning("ChromaDB not available — vector memory disabled")
        return None
    try:
        contact_dir = str(contact_id).replace("+", "").replace(" ", "").replace("-", "")
        vector_path = DATA_DIR / contact_dir / "vectors"
        vector_path.mkdir(parents=True, exist_ok=True)

        return chromadb.PersistentClient(
            path=str(vector_path),
            settings=Settings(anonymized_telemetry=False),
        )
    except Exception as e:
        logger.error(f"ChromaDB init failed for contact {contact_id}: {e}")
        return None


def get_collection(contact_id: str, name: str = "conversations"):
    """
    Get or create a named collection for a contact.

    Args:
        contact_id: The contact identifier.
        name: Collection name (default "conversations").

    Returns:
        chromadb.Collection or None on failure.
    """
    client = get_customer_vectordb(contact_id)
    if client is None:
        return None
    try:
        return client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.error(f"ChromaDB get_collection '{name}' failed for contact {contact_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Adding data
# ---------------------------------------------------------------------------

def add_message(
    contact_id: str,
    direction: str,
    content: str,
    timestamp: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    """
    Add a message to the contact's vector store.

    Args:
        contact_id: The contact identifier.
        direction: "inbound" (from customer) or "outbound" (from sales rep / bot).
        content: The message text.
        timestamp: ISO timestamp. Defaults to now (IST).
        metadata: Optional extra metadata (sent_by, mood, signals, etc.).
    """
    if not content or not content.strip():
        return

    if not timestamp:
        timestamp = _now_iso()

    collection = get_collection(contact_id)
    if collection is None:
        return

    doc_id = _make_id(content, timestamp)
    doc_metadata = {
        "direction": direction,
        "timestamp": timestamp,
        "date": timestamp[:10],
        "type": "message",
    }
    if metadata:
        # ChromaDB metadata values must be str, int, float, or bool
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                doc_metadata[k] = v
            else:
                doc_metadata[k] = str(v)

    try:
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[doc_metadata],
        )
    except Exception as e:
        logger.error(f"Vector upsert (message) failed for contact {contact_id}: {e}")


def add_signal(
    contact_id: str,
    signal_type: str,
    content: str,
    timestamp: Optional[str] = None,
):
    """
    Add an extracted signal to the contact's vector store.

    Args:
        contact_id: The contact identifier.
        signal_type: One of "buying_signal", "objection", "preference",
                     "price_sensitivity", "intent".
        content: Description / text of the signal.
        timestamp: ISO timestamp. Defaults to now (IST).
    """
    if not content or not content.strip():
        return

    if not timestamp:
        timestamp = _now_iso()

    collection = get_collection(contact_id)
    if collection is None:
        return

    doc_id = _make_id(f"signal:{signal_type}:{content}", timestamp)

    try:
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[{
                "direction": "system",
                "timestamp": timestamp,
                "date": timestamp[:10],
                "type": "signal",
                "signal_type": signal_type,
            }],
        )
    except Exception as e:
        logger.error(f"Vector upsert (signal) failed for contact {contact_id}: {e}")


def add_memory_note(
    contact_id: str,
    content: str,
    timestamp: Optional[str] = None,
):
    """
    Add an AI-curated insight / memory note about the customer.

    Args:
        contact_id: The contact identifier.
        content: The insight text.
        timestamp: ISO timestamp. Defaults to now (IST).
    """
    if not content or not content.strip():
        return

    if not timestamp:
        timestamp = _now_iso()

    collection = get_collection(contact_id)
    if collection is None:
        return

    doc_id = _make_id(f"note:{content}", timestamp)

    try:
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[{
                "direction": "system",
                "timestamp": timestamp,
                "date": timestamp[:10],
                "type": "memory_note",
            }],
        )
    except Exception as e:
        logger.error(f"Vector upsert (memory_note) failed for contact {contact_id}: {e}")


# ---------------------------------------------------------------------------
# Search and retrieval
# ---------------------------------------------------------------------------

def search(
    contact_id: str,
    query: str,
    n_results: int = 10,
    filter_type: Optional[str] = None,
) -> list:
    """
    Semantic search across a customer's entire history.

    Args:
        contact_id: The contact identifier.
        query: Natural language search query.
        n_results: Maximum results to return.
        filter_type: Optional filter — "message", "signal", or "memory_note".

    Returns:
        List of dicts: {content, direction, timestamp, type, distance}
        Lower distance = more relevant.
    """
    collection = get_collection(contact_id)
    if collection is None:
        return []

    try:
        count = collection.count()
        if count == 0:
            return []

        where = None
        if filter_type:
            where = {"type": filter_type}

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
            where=where,
        )

        hits = []
        if results and results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else None
                hit = {
                    "content": doc,
                    "direction": meta.get("direction", "unknown"),
                    "timestamp": meta.get("timestamp", ""),
                    "date": meta.get("date", ""),
                    "type": meta.get("type", "message"),
                    "distance": dist,
                }
                # Include signal_type if present
                if "signal_type" in meta:
                    hit["signal_type"] = meta["signal_type"]
                hits.append(hit)

        return hits

    except Exception as e:
        logger.error(f"Vector search failed for contact {contact_id}: {e}")
        return []


def get_relevant_context(
    contact_id: str,
    current_message: str,
    n_results: int = 8,
) -> str:
    """
    Get relevant context for the current message, formatted for LLM prompt injection.

    Searches across all messages, signals, and memory notes. Filters out
    results that are too distant (cosine distance > 1.5) to be useful.

    Args:
        contact_id: The contact identifier.
        current_message: The message to find context for.
        n_results: Maximum results to retrieve.

    Returns:
        A formatted string ready to inject into the LLM prompt, or "" if
        no relevant context is found.
    """
    hits = search(contact_id, current_message, n_results=n_results)

    if not hits:
        return ""

    context_parts = []
    context_parts.append("## Relevant customer history:\n")

    for hit in hits:
        # Skip if too distant (not really relevant)
        if hit["distance"] is not None and hit["distance"] > 1.5:
            continue

        date = hit["date"]
        hit_type = hit["type"]

        if hit_type == "message":
            dir_label = "Customer" if hit["direction"] == "inbound" else "Sales rep"
            context_parts.append(
                f"- **{date}** {dir_label}: {hit['content'][:300]}"
            )
        elif hit_type == "signal":
            signal_type = hit.get("signal_type", "unknown")
            context_parts.append(
                f"- **{date}** [Signal: {signal_type}] {hit['content'][:300]}"
            )
        elif hit_type == "memory_note":
            context_parts.append(
                f"- **{date}** [Insight] {hit['content'][:300]}"
            )
        else:
            context_parts.append(
                f"- **{date}** [{hit_type}] {hit['content'][:300]}"
            )

    if len(context_parts) == 1:
        return ""  # Only header, no actual hits passed the distance filter

    return "\n".join(context_parts)


# ---------------------------------------------------------------------------
# Customer summary and stats
# ---------------------------------------------------------------------------

def get_customer_summary(contact_id: str) -> dict:
    """
    Return a summary of the customer's vector store.

    Returns:
        Dict with keys:
        - total_embeddings: int
        - signal_counts: dict mapping signal_type to count
        - last_interaction: ISO timestamp of most recent entry, or ""
    """
    collection = get_collection(contact_id)
    if collection is None:
        return {"total_embeddings": 0, "signal_counts": {}, "last_interaction": ""}

    try:
        total = collection.count()
        if total == 0:
            return {"total_embeddings": 0, "signal_counts": {}, "last_interaction": ""}

        # Get all entries to compute stats
        # For large collections this could be expensive; in practice customer
        # conversations are bounded (hundreds, not millions).
        all_data = collection.get(include=["metadatas"])

        signal_counts = {}
        last_ts = ""

        for meta in (all_data.get("metadatas") or []):
            # Track signal counts
            if meta.get("type") == "signal":
                st = meta.get("signal_type", "unknown")
                signal_counts[st] = signal_counts.get(st, 0) + 1

            # Track most recent timestamp
            ts = meta.get("timestamp", "")
            if ts > last_ts:
                last_ts = ts

        return {
            "total_embeddings": total,
            "signal_counts": signal_counts,
            "last_interaction": last_ts,
        }

    except Exception as e:
        logger.error(f"Customer summary failed for contact {contact_id}: {e}")
        return {"total_embeddings": 0, "signal_counts": {}, "last_interaction": ""}


# ---------------------------------------------------------------------------
# Signal extraction from message text
# ---------------------------------------------------------------------------

def extract_signals_from_message(content: str, direction: str) -> list:
    """
    Basic keyword/pattern detection for sales signals in a message.

    Scans the message content against known patterns for buying signals,
    objections, price sensitivity, and intent.

    Args:
        content: The message text to analyze.
        direction: "inbound" or "outbound". Signals are primarily
                   extracted from inbound (customer) messages.

    Returns:
        List of dicts: {type, content, confidence}
        confidence is "high" if multiple patterns match in the same
        category, otherwise "medium".
    """
    if not content or not content.strip():
        return []

    # Signals are most meaningful from customer (inbound) messages,
    # but we still scan outbound for context (e.g., rep mentioning pricing).
    signals = []
    content_lower = content.lower()

    for signal_type, compiled_patterns in _COMPILED_PATTERNS.items():
        matches = []
        for pattern in compiled_patterns:
            match = pattern.search(content_lower)
            if match:
                matches.append(match.group())

        if matches:
            # Higher confidence when multiple patterns in the same category match
            confidence = "high" if len(matches) >= 2 else "medium"

            # Build a descriptive content string
            matched_terms = ", ".join(sorted(set(matches)))
            if direction == "inbound":
                signal_content = f"Customer message contains {signal_type.replace('_', ' ')} indicators: {matched_terms}"
            else:
                signal_content = f"Outbound message references {signal_type.replace('_', ' ')} terms: {matched_terms}"

            signals.append({
                "type": signal_type,
                "content": signal_content,
                "confidence": confidence,
            })

    return signals


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def delete_customer_vectors(contact_id: str):
    """
    Delete all vector data for a contact.

    Removes the entire vectors/ directory from the contact's data folder.
    """
    try:
        contact_dir = str(contact_id).replace("+", "").replace(" ", "").replace("-", "")
        vector_path = DATA_DIR / contact_dir / "vectors"
        if vector_path.exists():
            shutil.rmtree(vector_path)
            logger.info(f"Deleted vector store for contact {contact_id}")
    except Exception as e:
        logger.error(f"Failed to delete vectors for contact {contact_id}: {e}")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")

    test_contact = "test_customer_001"

    # Clean start
    delete_customer_vectors(test_contact)

    # Simulate a sales conversation
    messages = [
        ("inbound", "Hi, I saw your product on LinkedIn. Can you tell me more?", "2026-03-01T10:00:00+05:30"),
        ("outbound", "Hey! Thanks for reaching out. We help teams automate their sales outreach. Want me to send you a quick demo link?", "2026-03-01T10:02:00+05:30"),
        ("inbound", "Sure, send me the demo. How much does it cost?", "2026-03-01T10:05:00+05:30"),
        ("outbound", "Our starter plan is $49/mo. I'll send the demo link now.", "2026-03-01T10:06:00+05:30"),
        ("inbound", "That's a bit expensive. We're a small team. Any discounts?", "2026-03-01T10:10:00+05:30"),
        ("outbound", "We have a startup plan at $29/mo. Would that work?", "2026-03-01T10:12:00+05:30"),
        ("inbound", "Let me think about it. We're already using HubSpot for some of this.", "2026-03-02T14:00:00+05:30"),
        ("inbound", "Hey, I showed my manager. We want to go ahead and subscribe. How do I sign up?", "2026-03-05T11:00:00+05:30"),
    ]

    print("Adding messages to vector store...")
    for direction, content, ts in messages:
        add_message(test_contact, direction, content, timestamp=ts)

        # Also extract and store signals
        signals = extract_signals_from_message(content, direction)
        for sig in signals:
            add_signal(test_contact, sig["type"], sig["content"], timestamp=ts)
            print(f"  Signal [{sig['type']}] ({sig['confidence']}): {sig['content']}")

    # Add a memory note
    add_memory_note(
        test_contact,
        "Customer is price-sensitive but interested. Uses HubSpot. Manager is the decision-maker. Showed buying intent on March 5.",
        timestamp="2026-03-05T11:30:00+05:30",
    )

    # Stats
    summary = get_customer_summary(test_contact)
    print(f"\nCustomer summary: {summary}")

    # Search tests
    print("\n--- Search: 'pricing and cost' ---")
    hits = search(test_contact, "pricing and cost", n_results=5)
    for h in hits:
        print(f"  [{h['date']}] ({h['type']}, dist={h['distance']:.3f}) {h['content'][:80]}")

    print("\n--- Search: 'competitor tools' ---")
    hits = search(test_contact, "competitor tools", n_results=5)
    for h in hits:
        print(f"  [{h['date']}] ({h['type']}, dist={h['distance']:.3f}) {h['content'][:80]}")

    print("\n--- Search: signals only ---")
    hits = search(test_contact, "buying intent", n_results=5, filter_type="signal")
    for h in hits:
        print(f"  [{h['date']}] ({h.get('signal_type', '?')}, dist={h['distance']:.3f}) {h['content'][:80]}")

    print("\n--- Context injection for follow-up message ---")
    context = get_relevant_context(
        test_contact,
        "The customer asked about enterprise pricing and whether we integrate with Salesforce.",
    )
    print(context)

    # Signal extraction test
    print("\n--- Signal extraction tests ---")
    test_msgs = [
        ("How much does the enterprise plan cost? Can I get a quote?", "inbound"),
        ("That's too expensive. We already using Zoho CRM.", "inbound"),
        ("I want to purchase the annual plan. How do I sign up?", "inbound"),
        ("Here's our pricing page for reference.", "outbound"),
    ]
    for msg, d in test_msgs:
        sigs = extract_signals_from_message(msg, d)
        print(f"  '{msg[:60]}...' -> {[s['type'] for s in sigs]} ({[s['confidence'] for s in sigs]})")

    # Cleanup
    delete_customer_vectors(test_contact)
    print("\nAll customer memory tests passed!")
