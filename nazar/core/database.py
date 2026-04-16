"""
Nazar — SQLite Database Layer

Replaces all JSON flat-file storage with SQLite via SQLAlchemy.
Uses synchronous SQLite access (via stdlib sqlite3) for simplicity
and compatibility with the existing synchronous module APIs.

Contact profile content and conversation messages remain encrypted at rest
using per-contact Fernet keys (same HKDF derivation as before).

The database stores encrypted blobs for PII, NOT plaintext.
Queryable fields (stage, score, tags, etc.) remain plaintext for indexing.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("nazar")

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "nazar.db"

# Thread-local storage for connections (one connection per thread)
_local = threading.local()


# ──────────────────────────────────────────────────────────────────────────────
# Connection management
# ──────────────────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """
    Get a thread-local SQLite connection with WAL mode enabled.
    WAL allows concurrent reads during writes — critical for a web server.
    """
    conn = getattr(_local, "connection", None)
    if conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.connection = conn
    return conn


@contextmanager
def get_db():
    """Context manager that provides a connection and commits on success."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_connection():
    """Close the thread-local connection (call on shutdown)."""
    conn = getattr(_local, "connection", None)
    if conn is not None:
        conn.close()
        _local.connection = None


# ──────────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Contacts: queryable fields in columns, PII in encrypted blob
CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    phone           TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    company         TEXT DEFAULT '',
    pipeline_stage  TEXT NOT NULL DEFAULT 'New',
    lead_score      INTEGER DEFAULT 0,
    deal_value      REAL DEFAULT 0.0,
    source          TEXT DEFAULT '',
    tags            TEXT DEFAULT '[]',         -- JSON array
    notes           TEXT DEFAULT '',
    assigned_to     TEXT DEFAULT NULL,
    opt_in          INTEGER DEFAULT 0,         -- boolean
    opt_in_date     TEXT DEFAULT NULL,
    total_messages  INTEGER DEFAULT 0,
    last_contacted_at TEXT DEFAULT NULL,
    last_replied_at   TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL,
    manual_stage_override INTEGER DEFAULT 0,  -- boolean: if 1, AI won't reclassify
    updated_at      TEXT DEFAULT NULL,
    UNIQUE(workspace_id, phone)
);
CREATE INDEX IF NOT EXISTS ix_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS ix_contacts_ws_phone ON contacts(workspace_id, phone);
CREATE INDEX IF NOT EXISTS ix_contacts_stage ON contacts(pipeline_stage);
CREATE INDEX IF NOT EXISTS ix_contacts_score ON contacts(lead_score);
CREATE INDEX IF NOT EXISTS ix_contacts_ws ON contacts(workspace_id);
CREATE INDEX IF NOT EXISTS ix_contacts_stage_score ON contacts(pipeline_stage, lead_score);

-- Messages: encrypted content, queryable metadata
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    direction       TEXT NOT NULL,              -- 'inbound' | 'outbound'
    content         TEXT NOT NULL DEFAULT '',   -- encrypted message body
    content_type    TEXT DEFAULT 'text',        -- text, image, document, audio, template
    sent_by         TEXT DEFAULT 'bot',         -- 'bot', 'human', 'campaign', etc.
    wa_message_id   TEXT DEFAULT NULL,
    status          TEXT DEFAULT NULL,          -- sent, delivered, read, failed
    media_path      TEXT DEFAULT NULL,
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_contact ON messages(contact_id);
CREATE INDEX IF NOT EXISTS ix_messages_contact_ts ON messages(contact_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_messages_wa_id ON messages(wa_message_id);
CREATE INDEX IF NOT EXISTS ix_messages_ws ON messages(workspace_id);

-- Campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    name            TEXT NOT NULL DEFAULT '',
    template_id     TEXT DEFAULT '',
    template_name   TEXT DEFAULT '',
    target_count    INTEGER DEFAULT 0,
    sent            INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    delivered       INTEGER DEFAULT 0,
    read_count      INTEGER DEFAULT 0,
    replied         INTEGER DEFAULT 0,
    not_on_whatsapp INTEGER DEFAULT 0,
    filter_stage    TEXT DEFAULT '',
    filter_tag      TEXT DEFAULT '',
    contact_ids     TEXT DEFAULT '[]',         -- JSON array
    reply_mode      TEXT DEFAULT 'auto_ai',
    campaign_kb     INTEGER DEFAULT 0,         -- boolean: has KB?
    status          TEXT DEFAULT 'completed',
    scheduled_at    TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    completed_at    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_campaigns_ws ON campaigns(workspace_id);

-- Handoff state (current bot on/off per contact)
CREATE TABLE IF NOT EXISTS handoff_states (
    contact_id      TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    bot_active      INTEGER DEFAULT 1,         -- boolean
    reason          TEXT DEFAULT '',
    triggered_by    TEXT DEFAULT '',
    triggered_at    TEXT DEFAULT NULL,
    detection_method TEXT DEFAULT '',
    contact_name    TEXT DEFAULT '',
    contact_phone   TEXT DEFAULT '',
    message_excerpt TEXT DEFAULT '',
    human_responded INTEGER DEFAULT 0,
    human_responded_at TEXT DEFAULT NULL,
    resumed_at      TEXT DEFAULT NULL,
    resumed_by      TEXT DEFAULT NULL,
    resume_reason   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_handoff_ws ON handoff_states(workspace_id);

-- Handoff events (audit trail)
CREATE TABLE IF NOT EXISTS handoff_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    contact_id      TEXT NOT NULL,
    event           TEXT NOT NULL,
    reason          TEXT DEFAULT '',
    actor           TEXT DEFAULT '',
    contact_name    TEXT DEFAULT '',
    contact_phone   TEXT DEFAULT '',
    detection_method TEXT DEFAULT '',
    message_excerpt TEXT DEFAULT '',
    bot_active      INTEGER DEFAULT 1,
    triggered_by    TEXT DEFAULT '',
    triggered_at    TEXT DEFAULT '',
    resumed_by      TEXT DEFAULT '',
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_handoff_events_contact ON handoff_events(contact_id);
CREATE INDEX IF NOT EXISTS ix_handoff_events_ts ON handoff_events(timestamp);
CREATE INDEX IF NOT EXISTS ix_handoff_events_ws ON handoff_events(workspace_id);

-- Reply modes (per-contact overrides)
CREATE TABLE IF NOT EXISTS reply_modes (
    contact_id      TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    mode            TEXT NOT NULL DEFAULT 'auto_ai',
    set_by          TEXT DEFAULT 'manual',
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reply_modes_ws ON reply_modes(workspace_id);

-- Campaign-contact associations
CREATE TABLE IF NOT EXISTS campaign_contacts (
    contact_id      TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY (contact_id)
);
CREATE INDEX IF NOT EXISTS ix_cc_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS ix_cc_ws ON campaign_contacts(workspace_id);

-- AI drafts
CREATE TABLE IF NOT EXISTS ai_drafts (
    contact_id      TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    draft           TEXT NOT NULL DEFAULT '',
    customer_message TEXT DEFAULT '',
    campaign_id     TEXT DEFAULT '',
    generated_at    TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    final_text      TEXT DEFAULT NULL,
    approved_at     TEXT DEFAULT NULL,
    rejected_at     TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS ix_drafts_status ON ai_drafts(status);
CREATE INDEX IF NOT EXISTS ix_drafts_ws ON ai_drafts(workspace_id);

-- Opt-outs
CREATE TABLE IF NOT EXISTS optouts (
    phone           TEXT NOT NULL,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    opted_out       INTEGER DEFAULT 1,
    date            TEXT NOT NULL,
    reason          TEXT DEFAULT '',
    original_message TEXT DEFAULT '',
    opted_in_again_at TEXT DEFAULT NULL,
    PRIMARY KEY (workspace_id, phone)
);

-- Assignments (conversation routing)
CREATE TABLE IF NOT EXISTS assignments (
    contact_id      TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    assigned_to     TEXT DEFAULT NULL,
    assigned_at     TEXT NOT NULL,
    assigned_by     TEXT DEFAULT '',
    status          TEXT DEFAULT 'active',
    resolved_at     TEXT DEFAULT NULL,
    resolved_by     TEXT DEFAULT NULL,
    transfer_log    TEXT DEFAULT '[]'           -- JSON array
);
CREATE INDEX IF NOT EXISTS ix_assignments_agent ON assignments(assigned_to);
CREATE INDEX IF NOT EXISTS ix_assignments_status ON assignments(status);
CREATE INDEX IF NOT EXISTS ix_assignments_ws ON assignments(workspace_id);

-- Saved segments
CREATE TABLE IF NOT EXISTS segments (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    name            TEXT NOT NULL,
    segment         TEXT NOT NULL DEFAULT '{}', -- JSON
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segments_ws ON segments(workspace_id);

-- Outbound webhooks
CREATE TABLE IF NOT EXISTS webhooks (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    url             TEXT NOT NULL,
    events          TEXT DEFAULT '["*"]',       -- JSON array
    secret          TEXT DEFAULT '',
    name            TEXT DEFAULT '',
    active          INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_triggered_at TEXT DEFAULT NULL,
    total_deliveries INTEGER DEFAULT 0,
    failed_deliveries INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_webhooks_ws ON webhooks(workspace_id);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    actor_id        TEXT DEFAULT 'system',
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT DEFAULT '',
    details         TEXT DEFAULT '{}',          -- JSON
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_resource ON audit_log(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS ix_audit_ws ON audit_log(workspace_id);

-- Contact groups (for campaign targeting)
CREATE TABLE IF NOT EXISTS contact_groups (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    color           TEXT DEFAULT '#6366f1',
    created_at      TEXT NOT NULL,
    updated_at      TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS ix_groups_ws ON contact_groups(workspace_id);

-- Group membership (many-to-many)
CREATE TABLE IF NOT EXISTS contact_group_members (
    group_id        TEXT NOT NULL REFERENCES contact_groups(id) ON DELETE CASCADE,
    contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    added_at        TEXT NOT NULL,
    PRIMARY KEY (group_id, contact_id)
);
CREATE INDEX IF NOT EXISTS ix_cgm_group ON contact_group_members(group_id);
CREATE INDEX IF NOT EXISTS ix_cgm_contact ON contact_group_members(contact_id);
CREATE INDEX IF NOT EXISTS ix_cgm_ws ON contact_group_members(workspace_id);

-- KB documents metadata (structured knowledge base)
CREATE TABLE IF NOT EXISTS kb_documents (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL DEFAULT 'default',
    title           TEXT NOT NULL,
    doc_type        TEXT DEFAULT 'text',
    scope           TEXT DEFAULT 'global',
    campaign_id     TEXT DEFAULT '',
    file_path       TEXT DEFAULT '',
    char_count      INTEGER DEFAULT 0,
    chunk_count     INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kb_docs_ws ON kb_documents(workspace_id);
CREATE INDEX IF NOT EXISTS ix_kb_docs_scope ON kb_documents(scope);
"""


# ──────────────────────────────────────────────────────────────────────────────
# Init
# ──────────────────────────────────────────────────────────────────────────────

def _migrate_add_workspace_id(conn: sqlite3.Connection):
    """
    Migration: add workspace_id column to all tables if missing.
    Safe to run multiple times — checks column existence first.
    """
    tables_needing_workspace = [
        "contacts", "messages", "campaigns", "handoff_states", "handoff_events",
        "reply_modes", "campaign_contacts", "ai_drafts", "optouts",
        "assignments", "segments", "webhooks", "audit_log",
    ]
    for table in tables_needing_workspace:
        try:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "workspace_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'")
                logger.info("Migration: added workspace_id to %s", table)
        except Exception as e:
            logger.warning("Migration skip for %s: %s", table, e)



def _migrate_add_new_columns(conn: sqlite3.Connection):
    """Add new columns to existing tables. Safe to run multiple times."""
    # Add manual_stage_override to contacts if missing
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()]
        if "manual_stage_override" not in cols:
            conn.execute("ALTER TABLE contacts ADD COLUMN manual_stage_override INTEGER DEFAULT 0")
            logger.info("Migration: added manual_stage_override to contacts")
    except Exception as e:
        logger.warning("Migration skip for manual_stage_override: %s", e)


def _needs_migration(conn: sqlite3.Connection) -> bool:
    """Check if any existing table is missing the workspace_id column."""
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()]
        if not tables:
            return False  # Fresh DB, no migration needed
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if cols and "workspace_id" not in cols:
                return True
        return False
    except Exception:
        return False


def init_db(db_path: Path = None):
    """
    Create all tables. Safe to call multiple times (CREATE IF NOT EXISTS).
    Call once on server startup. Runs migrations for existing databases.

    Order matters: if the DB already has tables without workspace_id,
    we must add the column BEFORE running the full schema (which creates
    indexes referencing workspace_id).
    """
    if db_path:
        global DB_PATH
        DB_PATH = db_path
        # Reset thread-local connection so it picks up the new path
        _local.connection = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        # Step 1: migrate existing tables (add workspace_id if missing)
        if _needs_migration(conn):
            _migrate_add_workspace_id(conn)
            conn.commit()
        # Step 2: run full schema (CREATE IF NOT EXISTS + indexes)
        conn.executescript(SCHEMA_SQL)
        # Step 3: run additional column migrations (always safe to run)
        _migrate_add_new_columns(conn)
        conn.commit()
    logger.info("Database initialized at %s", DB_PATH)


def reset_db(workspace_id: str = None):
    """
    Drop all data (for testing). Does NOT drop schema.
    If workspace_id is provided, only deletes data for that workspace.
    """
    tables = [
        "messages", "campaign_contacts", "ai_drafts", "reply_modes",
        "handoff_events", "handoff_states", "optouts", "assignments",
        "segments", "webhooks", "audit_log", "campaigns",
        "contact_group_members", "contact_groups", "kb_documents", "contacts",
    ]
    with get_db() as conn:
        for t in tables:
            if workspace_id:
                conn.execute(f"DELETE FROM {t} WHERE workspace_id = ?", (workspace_id,))
            else:
                conn.execute(f"DELETE FROM {t}")


# ──────────────────────────────────────────────────────────────────────────────
# Helper: dict ↔ Row
# ──────────────────────────────────────────────────────────────────────────────

def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows) -> list:
    """Convert a list of sqlite3.Row to a list of dicts."""
    return [dict(r) for r in rows]
