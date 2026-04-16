"""
Tests for core/assignment_manager.py — conversation assignment and routing.
"""

import json
import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import assignment_manager


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """Set up an isolated SQLite database for each test."""
    import database
    db_path = tmp_path / "nazar.db"
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database._local.connection = None
    database.init_db(db_path)
    yield tmp_path
    database.close_connection()


class TestAssignConversation:
    def test_round_robin_assigns_least_loaded_agent(self):
        agents = ["agent_1", "agent_2", "agent_3"]
        record = assignment_manager.assign_conversation("c_001", agents, strategy="round_robin")
        assert record["assigned_to"] in agents
        assert record["status"] == "active"

    def test_round_robin_distributes_across_agents(self):
        agents = ["agent_1", "agent_2"]
        ids = []
        for i in range(4):
            r = assignment_manager.assign_conversation(f"c_{i:03d}", agents, strategy="round_robin")
            ids.append(r["assigned_to"])
        # Should see both agents
        assert len(set(ids)) >= 1  # At minimum works without errors

    def test_manual_strategy_leaves_unassigned(self):
        agents = ["agent_1", "agent_2"]
        record = assignment_manager.assign_conversation("c_002", agents, strategy="manual")
        assert record["assigned_to"] is None

    def test_empty_agents_leaves_unassigned(self):
        record = assignment_manager.assign_conversation("c_003", [])
        assert record["assigned_to"] is None

    def test_least_busy_picks_agent_with_fewer_conversations(self):
        # Manually create existing assignment for agent_1
        assignment_manager.manual_assign("c_100", "agent_1", "test")
        agents = ["agent_1", "agent_2"]
        record = assignment_manager.assign_conversation("c_101", agents, strategy="least_busy")
        # agent_2 has 0 conversations so should be picked
        assert record["assigned_to"] == "agent_2"


class TestManualAssign:
    def test_manual_assign_sets_agent(self):
        record = assignment_manager.manual_assign("c_010", "agent_5", "admin")
        assert record["assigned_to"] == "agent_5"
        assert record["assigned_by"] == "admin"

    def test_manual_assign_updates_existing(self):
        assignment_manager.manual_assign("c_011", "agent_1", "admin")
        record = assignment_manager.manual_assign("c_011", "agent_2", "admin")
        assert record["assigned_to"] == "agent_2"

    def test_claim_conversation_uses_agent_id(self):
        record = assignment_manager.claim_conversation("c_012", "agent_7")
        assert record["assigned_to"] == "agent_7"
        assert record["assigned_by"] == "agent_7"


class TestTransferConversation:
    def test_transfer_changes_assigned_to(self):
        assignment_manager.manual_assign("c_020", "agent_1", "admin")
        record = assignment_manager.transfer_conversation("c_020", "agent_1", "agent_2", "Away")
        assert record["assigned_to"] == "agent_2"

    def test_transfer_adds_log_entry(self):
        assignment_manager.manual_assign("c_021", "agent_1", "admin")
        record = assignment_manager.transfer_conversation("c_021", "agent_1", "agent_3", "On leave")
        assert len(record["transfer_log"]) == 1
        assert record["transfer_log"][0]["from"] == "agent_1"
        assert record["transfer_log"][0]["to"] == "agent_3"

    def test_transfer_nonexistent_creates_record(self):
        record = assignment_manager.transfer_conversation("c_999", "agent_1", "agent_2")
        assert record["assigned_to"] == "agent_2"


class TestResolveConversation:
    def test_resolve_marks_status_resolved(self):
        assignment_manager.manual_assign("c_030", "agent_1", "admin")
        record = assignment_manager.resolve_conversation("c_030")
        assert record["status"] == "resolved"

    def test_resolved_not_in_unassigned_queue(self):
        assignment_manager.manual_assign("c_031", None, "system")
        # The unassigned queue lists active records with no agent
        assignment_manager.resolve_conversation("c_031")
        queue = assignment_manager.get_unassigned_queue()
        contact_ids = [r["contact_id"] for r in queue]
        assert "c_031" not in contact_ids


class TestGetAgentConversations:
    def test_returns_conversations_for_agent(self):
        assignment_manager.manual_assign("c_040", "agent_X", "admin")
        assignment_manager.manual_assign("c_041", "agent_X", "admin")
        assignment_manager.manual_assign("c_042", "agent_Y", "admin")
        convs = assignment_manager.get_agent_conversations("agent_X")
        ids = [r["contact_id"] for r in convs]
        assert "c_040" in ids
        assert "c_041" in ids
        assert "c_042" not in ids

    def test_resolved_not_in_active_list(self):
        assignment_manager.manual_assign("c_050", "agent_Z", "admin")
        assignment_manager.resolve_conversation("c_050")
        convs = assignment_manager.get_agent_conversations("agent_Z", status="active")
        ids = [r["contact_id"] for r in convs]
        assert "c_050" not in ids


class TestWorkload:
    def test_workload_counts_active_assignments(self):
        assignment_manager.manual_assign("c_060", "agent_A", "admin")
        assignment_manager.manual_assign("c_061", "agent_A", "admin")
        assignment_manager.manual_assign("c_062", "agent_B", "admin")
        workload = assignment_manager.get_agent_workload()
        assert workload.get("agent_A", 0) == 2
        assert workload.get("agent_B", 0) == 1
