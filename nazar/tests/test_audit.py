"""
Tests for core/audit.py — audit log system.
"""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import audit


@pytest.fixture(autouse=True)
def tmp_audit_dir(tmp_path, monkeypatch):
    """Redirect audit log directory to a temp path."""
    monkeypatch.setattr(audit, "DATA_DIR", tmp_path)
    yield tmp_path


class TestLogAudit:
    def test_returns_entry_dict(self):
        entry = audit.log_audit("contact.created", "contact", "c_001")
        assert isinstance(entry, dict)
        assert entry["action"] == "contact.created"
        assert entry["resource_type"] == "contact"
        assert entry["resource_id"] == "c_001"

    def test_entry_has_id_and_timestamp(self):
        entry = audit.log_audit("test.action", "test")
        assert "id" in entry
        assert "timestamp" in entry
        assert len(entry["id"]) > 0

    def test_default_actor_is_system(self):
        entry = audit.log_audit("contact.updated", "contact", "c_002")
        assert entry["actor_id"] == "system"

    def test_custom_actor_id(self):
        entry = audit.log_audit("user.login", "user", "usr_abc", actor_id="usr_abc")
        assert entry["actor_id"] == "usr_abc"

    def test_details_stored(self):
        entry = audit.log_audit(
            "contact.stage_changed", "contact", "c_003",
            details={"from": "New", "to": "Qualified"}
        )
        assert entry["details"]["from"] == "New"
        assert entry["details"]["to"] == "Qualified"

    def test_entry_written_to_file(self, tmp_path):
        audit.log_audit("campaign.sent", "campaign", "cmp_001")
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["action"] == "campaign.sent"

    def test_multiple_entries_append(self, tmp_path):
        audit.log_audit("a.1", "test", "r1")
        audit.log_audit("a.2", "test", "r2")
        audit.log_audit("a.3", "test", "r3")
        files = list(tmp_path.glob("*.jsonl"))
        total_lines = sum(len(f.read_text().splitlines()) for f in files)
        assert total_lines == 3


class TestGetAuditLog:
    def test_returns_list(self):
        audit.log_audit("x.y", "z")
        entries = audit.get_audit_log(days=1)
        assert isinstance(entries, list)

    def test_filter_by_action_prefix(self):
        audit.log_audit("contact.created", "contact", "c_1")
        audit.log_audit("campaign.sent", "campaign", "camp_1")
        entries = audit.get_audit_log(days=1, action="contact")
        assert all(e["action"].startswith("contact") for e in entries)

    def test_filter_by_resource_type(self):
        audit.log_audit("contact.updated", "contact", "c_2")
        audit.log_audit("draft.approved", "draft", "c_3")
        entries = audit.get_audit_log(days=1, resource_type="draft")
        assert all(e["resource_type"] == "draft" for e in entries)

    def test_filter_by_actor_id(self):
        audit.log_audit("user.logout", "user", actor_id="usr_999")
        audit.log_audit("user.login", "user", actor_id="usr_001")
        entries = audit.get_audit_log(days=1, actor_id="usr_999")
        assert all(e["actor_id"] == "usr_999" for e in entries)

    def test_limit_respected(self):
        for i in range(10):
            audit.log_audit(f"action.{i}", "test")
        entries = audit.get_audit_log(days=1, limit=3)
        assert len(entries) <= 3

    def test_newest_first_ordering(self):
        audit.log_audit("first", "test")
        audit.log_audit("second", "test")
        entries = audit.get_audit_log(days=1)
        # Newest first — last logged should come first
        assert entries[0]["action"] == "second"

    def test_empty_log_returns_empty_list(self):
        entries = audit.get_audit_log(days=1)
        assert entries == []


class TestGetAuditStats:
    def test_stats_has_total_entries(self):
        audit.log_audit("a.b", "test")
        stats = audit.get_audit_stats(days=1)
        assert stats["total_entries"] >= 1

    def test_stats_by_action(self):
        audit.log_audit("contact.created", "contact")
        audit.log_audit("contact.created", "contact")
        audit.log_audit("draft.approved", "draft")
        stats = audit.get_audit_stats(days=1)
        assert stats["by_action"].get("contact.created", 0) >= 2
        assert stats["by_action"].get("draft.approved", 0) >= 1
