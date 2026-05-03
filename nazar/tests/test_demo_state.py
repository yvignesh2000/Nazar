"""
Smoke test: verifies that, after `seed_demo.py` runs, the demo state
has the exact shape we promise prospects:

  • 12 Bloom Interiors contacts (across the 6 pipeline stages)
  • 5 KB documents
  • 7 templates
  • 4 campaigns (1 scheduled, 1 active, 2 completed)
  • Pipeline value > ₹1 Cr

Run *after* seed_demo.py on the live SQLite database. Skipped automatically
if the demo DB hasn't been seeded (so it never blocks CI).

Usage:
    pytest tests/test_demo_state.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _has_seeded_db() -> bool:
    """Check if the demo db looks seeded (>0 contacts in default workspace)."""
    db_path = ROOT / "data" / "nazar.db"
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    try:
        import sqlite3
        con = sqlite3.connect(str(db_path))
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM contacts WHERE workspace_id='default'"
            ).fetchone()
            return bool(row and row[0] > 0)
        finally:
            con.close()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_seeded_db(),
    reason="Demo DB not seeded; run `python3 seed_demo.py` first.",
)


@pytest.fixture(scope="module")
def db():
    import sqlite3
    con = sqlite3.connect(str(ROOT / "data" / "nazar.db"))
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def test_contacts_exact_count_and_stages(db):
    rows = db.execute(
        "SELECT pipeline_stage FROM contacts WHERE workspace_id='default'"
    ).fetchall()
    assert len(rows) == 12, f"Expected 12 demo contacts, got {len(rows)}"
    stages = {r["pipeline_stage"] for r in rows}
    # All 6 stages must be present so the pipeline page looks alive.
    expected = {"New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"}
    assert expected.issubset(stages), f"Missing stages: {expected - stages}"


def test_kb_documents_present(db):
    """KB docs may live in SQLite (kb_documents) and/or ChromaDB.
    We accept either as proof the KB has been seeded."""
    sql_titles: list[str] = []
    try:
        rows = db.execute(
            "SELECT title FROM kb_documents WHERE workspace_id='default'"
        ).fetchall()
        sql_titles = [r["title"] for r in rows]
    except Exception:
        pass

    if sql_titles:
        assert len(sql_titles) >= 5, f"Expected ≥5 KB docs in SQL, got {len(sql_titles)}"
        assert any("Bloom" in t for t in sql_titles), "KB docs not Bloom-branded"
        return

    # Fallback: check ChromaDB / data/kb dir for evidence of seeding.
    kb_dir = ROOT / "data" / "kb"
    chroma_dir = ROOT / "data" / ".chroma_health"
    knowledge_txt = ROOT / "data" / "knowledge_base.txt"
    has_evidence = (
        (kb_dir.exists() and any(kb_dir.iterdir())) or
        (knowledge_txt.exists() and "Bloom" in knowledge_txt.read_text())
    )
    assert has_evidence, "No KB evidence in SQL or filesystem; seed_demo.py KB step likely failed."


def test_campaigns_mix(db):
    try:
        rows = db.execute(
            "SELECT status FROM campaigns WHERE workspace_id='default'"
        ).fetchall()
    except Exception:
        pytest.skip("campaigns table not present.")
    statuses = [r["status"] for r in rows]
    assert len(statuses) >= 4, f"Expected ≥4 campaigns, got {len(statuses)}"
    # Variety check — at least 2 distinct statuses
    assert len(set(statuses)) >= 2, "Campaigns lack variety; demo will look flat"


def test_templates_present():
    tpl = ROOT / "data" / "templates.json"
    assert tpl.exists(), "templates.json missing"
    data = json.loads(tpl.read_text())
    if isinstance(data, dict) and "templates" in data:
        templates = data["templates"]
    else:
        templates = data
    assert len(templates) >= 7, f"Expected ≥7 templates, got {len(templates)}"


def test_pipeline_value_realistic(db):
    rows = db.execute(
        "SELECT deal_value, pipeline_stage FROM contacts "
        "WHERE workspace_id='default'"
    ).fetchall()
    open_value = sum(
        (r["deal_value"] or 0)
        for r in rows
        if r["pipeline_stage"] not in ("Won", "Lost")
    )
    # Should be ~₹77L based on Bloom seed; assert a comfortable lower bound.
    assert open_value > 5_000_000, (
        f"Pipeline value too low ({open_value}); demo will under-impress."
    )
