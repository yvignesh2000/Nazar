"""
Tests for Nazar — Multi-tenancy (workspace isolation)

Tests cover:
- workspace_id column in contacts
- Workspace-scoped contact creation and listing
- Same phone number in different workspaces
- workspace_context thread-local
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))


class TestWorkspaceContext:
    """Test the thread-local workspace context."""

    def test_default_workspace(self):
        from workspace_context import get_workspace, DEFAULT_WORKSPACE
        assert get_workspace() == DEFAULT_WORKSPACE

    def test_set_and_get(self):
        from workspace_context import set_workspace, get_workspace
        set_workspace("ws_test_123")
        assert get_workspace() == "ws_test_123"

    def test_clear_resets_to_default(self):
        from workspace_context import set_workspace, get_workspace, clear_workspace, DEFAULT_WORKSPACE
        set_workspace("ws_custom")
        assert get_workspace() == "ws_custom"
        clear_workspace()
        assert get_workspace() == DEFAULT_WORKSPACE


class TestContactWorkspaceIsolation:
    """Test that contacts are isolated between workspaces."""

    def test_create_contact_default_workspace(self, tmp_data_dir):
        from contact_manager import create_contact
        c = create_contact("Alice", "+919999900001")
        assert c["workspace_id"] == "default"

    def test_create_contact_custom_workspace(self, tmp_data_dir):
        from contact_manager import create_contact
        c = create_contact("Bob", "+919999900002", workspace_id="ws_acme")
        assert c["workspace_id"] == "ws_acme"

    def test_same_phone_different_workspaces(self, tmp_data_dir):
        from contact_manager import create_contact
        phone = "+919999900003"
        c1 = create_contact("Alice WS1", phone, workspace_id="ws_one")
        c2 = create_contact("Alice WS2", phone, workspace_id="ws_two")
        assert c1["contact_id"] != c2["contact_id"]
        assert c1["name"] == "Alice WS1"
        assert c2["name"] == "Alice WS2"

    def test_same_phone_same_workspace_raises(self, tmp_data_dir):
        from contact_manager import create_contact
        phone = "+919999900004"
        create_contact("Alice", phone, workspace_id="ws_dup")
        with pytest.raises(ValueError, match="already exists"):
            create_contact("Alice Clone", phone, workspace_id="ws_dup")

    def test_list_contacts_scoped_to_workspace(self, tmp_data_dir):
        from contact_manager import create_contact, list_contacts

        create_contact("WS1 Contact", "+919999900005", workspace_id="ws_alpha")
        create_contact("WS2 Contact", "+919999900006", workspace_id="ws_beta")
        create_contact("WS1 Contact 2", "+919999900007", workspace_id="ws_alpha")

        ws1_list = list_contacts(workspace_id="ws_alpha")
        ws2_list = list_contacts(workspace_id="ws_beta")

        assert len(ws1_list) == 2
        assert len(ws2_list) == 1
        assert ws2_list[0]["name"] == "WS2 Contact"

    def test_get_contact_by_phone_scoped(self, tmp_data_dir):
        from contact_manager import create_contact, get_contact_by_phone

        phone = "+919999900008"
        create_contact("Alpha User", phone, workspace_id="ws_alpha")
        create_contact("Beta User", phone, workspace_id="ws_beta")

        alpha = get_contact_by_phone(phone, workspace_id="ws_alpha")
        beta = get_contact_by_phone(phone, workspace_id="ws_beta")

        assert alpha["name"] == "Alpha User"
        assert beta["name"] == "Beta User"
        assert alpha["contact_id"] != beta["contact_id"]

    def test_contact_exists_scoped(self, tmp_data_dir):
        from contact_manager import create_contact, contact_exists

        phone = "+919999900009"
        create_contact("Only in Alpha", phone, workspace_id="ws_alpha")

        assert contact_exists(phone, workspace_id="ws_alpha") is True
        assert contact_exists(phone, workspace_id="ws_beta") is False

    def test_pipeline_summary_scoped(self, tmp_data_dir):
        from contact_manager import create_contact, move_stage, get_pipeline_summary

        c1 = create_contact("Won1", "+919999900010", workspace_id="ws_x")
        c2 = create_contact("Won2", "+919999900011", workspace_id="ws_y")
        move_stage(c1["contact_id"], "Won")
        move_stage(c2["contact_id"], "Qualified")

        summary_x = get_pipeline_summary(workspace_id="ws_x")
        summary_y = get_pipeline_summary(workspace_id="ws_y")

        assert summary_x["Won"]["count"] == 1
        assert summary_x["Qualified"]["count"] == 0
        assert summary_y["Qualified"]["count"] == 1
        assert summary_y["Won"]["count"] == 0


class TestDatabaseMigration:
    """Test that migration adds workspace_id safely."""

    def test_init_db_creates_workspace_columns(self, tmp_data_dir):
        from database import get_db

        with get_db() as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()]
            assert "workspace_id" in cols

            cols_msg = [row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()]
            assert "workspace_id" in cols_msg

            cols_camp = [row[1] for row in conn.execute("PRAGMA table_info(campaigns)").fetchall()]
            assert "workspace_id" in cols_camp

    def test_workspace_id_defaults_to_default(self, tmp_data_dir):
        from database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO contacts (id, phone, name, created_at) VALUES (?, ?, ?, ?)",
                ("test1", "+910000", "Test", "2025-01-01")
            )
            row = conn.execute("SELECT workspace_id FROM contacts WHERE id = 'test1'").fetchone()
            assert row["workspace_id"] == "default"
