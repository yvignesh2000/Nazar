"""
Tests for core/segmentation.py — contact segmentation engine.
"""

import json
import pytest
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import segmentation


# ──────────────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))


def _ts(days_ago: int) -> str:
    return (datetime.now(IST) - timedelta(days=days_ago)).isoformat()


CONTACTS = [
    {
        "contact_id": "c_001", "name": "Alice", "pipeline_stage": "Qualified",
        "lead_score": 75, "tags": ["enterprise", "hot"],
        "deal_value": 50000, "source": "LinkedIn",
        "company": "Acme Corp", "opt_out": False,
        "last_contacted_at": _ts(2), "created_at": _ts(30),
    },
    {
        "contact_id": "c_002", "name": "Bob", "pipeline_stage": "New",
        "lead_score": 30, "tags": ["cold"],
        "deal_value": 10000, "source": "Website",
        "company": "Bob Ltd", "opt_out": False,
        "last_contacted_at": _ts(10), "created_at": _ts(60),
    },
    {
        "contact_id": "c_003", "name": "Carol", "pipeline_stage": "Proposal",
        "lead_score": 85, "tags": ["enterprise"],
        "deal_value": 100000, "source": "Referral",
        "company": "Carol Inc", "opt_out": False,
        "last_contacted_at": _ts(1), "created_at": _ts(15),
    },
    {
        "contact_id": "c_004", "name": "Dave (opted out)", "pipeline_stage": "Qualified",
        "lead_score": 90, "tags": ["enterprise"],
        "deal_value": 200000, "source": "Event",
        "company": "Dave Corp", "opt_out": True,
        "last_contacted_at": _ts(3), "created_at": _ts(20),
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Basic evaluation
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateSegment:
    def test_empty_conditions_returns_all_non_opted_out(self):
        result = segmentation.evaluate_segment(CONTACTS, {"conditions": [], "logic": "AND"})
        # Dave is opted out — should be excluded
        ids = [c["contact_id"] for c in result]
        assert "c_004" not in ids
        assert len(result) == 3

    def test_eq_stage_filter(self):
        seg = {"conditions": [{"field": "pipeline_stage", "operator": "eq", "value": "Qualified"}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        # c_001 is Qualified; c_004 is Qualified but opted out
        assert len(result) == 1
        assert result[0]["contact_id"] == "c_001"

    def test_gte_lead_score(self):
        seg = {"conditions": [{"field": "lead_score", "operator": "gte", "value": 80}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_003" in ids   # score 85
        assert "c_001" not in ids  # score 75
        assert "c_004" not in ids  # opted out

    def test_contains_tag(self):
        seg = {"conditions": [{"field": "tags", "operator": "contains", "value": "enterprise"}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_001" in ids
        assert "c_003" in ids
        assert "c_002" not in ids  # only has "cold"
        assert "c_004" not in ids  # opted out

    def test_in_operator_multiple_stages(self):
        seg = {"conditions": [
            {"field": "pipeline_stage", "operator": "in", "value": ["Qualified", "Proposal"]}
        ]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_001" in ids
        assert "c_003" in ids
        assert "c_002" not in ids

    def test_lt_deal_value(self):
        seg = {"conditions": [{"field": "deal_value", "operator": "lt", "value": 20000}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_002" in ids
        assert "c_001" not in ids

    def test_last_contact_days_gte(self):
        seg = {"conditions": [{"field": "last_contact_days", "operator": "gte", "value": 5}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_002" in ids  # 10 days ago
        assert "c_001" not in ids  # 2 days ago

    def test_opted_out_always_excluded(self):
        # Even with a segment that would normally match Dave
        seg = {"conditions": [{"field": "lead_score", "operator": "gte", "value": 0}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_004" not in ids


# ──────────────────────────────────────────────────────────────────────────────
# AND / OR logic
# ──────────────────────────────────────────────────────────────────────────────

class TestSegmentLogic:
    def test_and_requires_all_conditions(self):
        seg = {
            "conditions": [
                {"field": "pipeline_stage", "operator": "eq", "value": "Qualified"},
                {"field": "lead_score", "operator": "gte", "value": 70},
            ],
            "logic": "AND",
        }
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_001" in ids  # Qualified + score 75

    def test_or_requires_any_condition(self):
        seg = {
            "conditions": [
                {"field": "pipeline_stage", "operator": "eq", "value": "New"},
                {"field": "lead_score", "operator": "gte", "value": 80},
            ],
            "logic": "OR",
        }
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_002" in ids  # New stage
        assert "c_003" in ids  # score 85
        assert "c_004" not in ids  # opted out

    def test_and_no_results_when_impossible_conditions(self):
        seg = {
            "conditions": [
                {"field": "pipeline_stage", "operator": "eq", "value": "Won"},
                {"field": "lead_score", "operator": "gte", "value": 99},
            ],
            "logic": "AND",
        }
        result = segmentation.evaluate_segment(CONTACTS, seg)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# Operators
# ──────────────────────────────────────────────────────────────────────────────

class TestOperators:
    def test_neq_operator(self):
        seg = {"conditions": [{"field": "pipeline_stage", "operator": "neq", "value": "New"}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        assert all(c["pipeline_stage"] != "New" for c in result)

    def test_exists_operator(self):
        seg = {"conditions": [{"field": "company", "operator": "exists", "value": None}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        assert len(result) == 3  # All non-opted-out have company

    def test_not_contains_operator(self):
        seg = {"conditions": [{"field": "tags", "operator": "not_contains", "value": "enterprise"}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_002" in ids  # only has "cold"
        assert "c_001" not in ids

    def test_starts_with_operator(self):
        seg = {"conditions": [{"field": "company", "operator": "starts_with", "value": "Acme"}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        ids = [c["contact_id"] for c in result]
        assert "c_001" in ids
        assert "c_002" not in ids

    def test_unknown_operator_returns_false(self):
        seg = {"conditions": [{"field": "lead_score", "operator": "invalid_op", "value": 50}]}
        result = segmentation.evaluate_segment(CONTACTS, seg)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# Preview
# ──────────────────────────────────────────────────────────────────────────────

class TestPreviewSegment:
    def test_preview_returns_count_and_sample(self):
        seg = {"conditions": [{"field": "lead_score", "operator": "gte", "value": 0}]}
        preview = segmentation.preview_segment(CONTACTS, seg, sample_size=2)
        assert "count" in preview
        assert "sample" in preview
        assert len(preview["sample"]) <= 2

    def test_preview_count_matches_full_evaluation(self):
        seg = {"conditions": [{"field": "pipeline_stage", "operator": "eq", "value": "Qualified"}]}
        full = segmentation.evaluate_segment(CONTACTS, seg)
        preview = segmentation.preview_segment(CONTACTS, seg)
        assert preview["count"] == len(full)


# ──────────────────────────────────────────────────────────────────────────────
# Saved segments
# ──────────────────────────────────────────────────────────────────────────────

class TestSavedSegments:
    @pytest.fixture(autouse=True)
    def tmp_segments(self, tmp_path, monkeypatch):
        monkeypatch.setattr(segmentation, "_SEGMENTS_PATH", tmp_path / "segments.json")

    def test_save_and_retrieve_segment(self):
        seg = {"conditions": [{"field": "lead_score", "operator": "gte", "value": 50}]}
        record = segmentation.save_segment("High Score", seg)
        assert record["name"] == "High Score"
        retrieved = segmentation.get_segment(record["id"])
        assert retrieved is not None
        assert retrieved["name"] == "High Score"

    def test_list_segments(self):
        seg = {"conditions": []}
        segmentation.save_segment("Seg 1", seg)
        segmentation.save_segment("Seg 2", seg)
        all_segs = segmentation.list_segments()
        names = [s["name"] for s in all_segs]
        assert "Seg 1" in names
        assert "Seg 2" in names

    def test_delete_segment(self):
        seg = {"conditions": []}
        record = segmentation.save_segment("To Delete", seg)
        deleted = segmentation.delete_segment(record["id"])
        assert deleted is True
        assert segmentation.get_segment(record["id"]) is None

    def test_delete_nonexistent_returns_false(self):
        assert segmentation.delete_segment("nonexistent_id") is False
