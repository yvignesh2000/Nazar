# -*- coding: utf-8 -*-
"""
Tests for multi-channel support:
  - core/channel.py (CRUD, lookup, default channel)
  - core/workspace_context.py (channel thread-local)
  - core/database.py (channels table, channel_id migration)
  - core/schemas.py (channel validation)
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from database import init_db, reset_db, get_db
from channel import (
    create_channel, get_channel, get_channel_by_phone_number_id,
    list_channels, update_channel, delete_channel, get_primary_channel,
    get_channel_config, get_channel_credentials, ensure_default_channel,
    channel_count, DEFAULT_CHANNEL,
)
from workspace_context import (
    set_workspace, get_workspace, clear_workspace,
    set_channel, get_channel as ctx_get_channel, clear_channel,
    clear_context, DEFAULT_WORKSPACE, DEFAULT_CHANNEL as CTX_DEFAULT_CHANNEL,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Each test gets a fresh database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    reset_db()
    set_workspace("default")
    set_channel("default")
    yield
    clear_context()


# ──────────────────────────────────────────────────────────────────────────────
# workspace_context.py — Channel context tests
# ──────────────────────────────────────────────────────────────────────────────

class TestChannelContext:
    """Test thread-local channel context."""

    def test_default_channel(self):
        clear_channel()
        assert ctx_get_channel() == CTX_DEFAULT_CHANNEL

    def test_set_and_get_channel(self):
        set_channel("ch_abc123")
        assert ctx_get_channel() == "ch_abc123"

    def test_clear_channel(self):
        set_channel("ch_abc123")
        clear_channel()
        assert ctx_get_channel() == CTX_DEFAULT_CHANNEL

    def test_clear_context_clears_both(self):
        set_workspace("ws_test")
        set_channel("ch_test")
        clear_context()
        assert get_workspace() == DEFAULT_WORKSPACE
        assert ctx_get_channel() == CTX_DEFAULT_CHANNEL

    def test_workspace_and_channel_independent(self):
        set_workspace("ws_a")
        set_channel("ch_b")
        assert get_workspace() == "ws_a"
        assert ctx_get_channel() == "ch_b"
        clear_workspace()
        assert get_workspace() == DEFAULT_WORKSPACE
        assert ctx_get_channel() == "ch_b"  # channel unaffected


# ──────────────────────────────────────────────────────────────────────────────
# database.py — channels table & channel_id migration tests
# ──────────────────────────────────────────────────────────────────────────────

class TestChannelSchema:
    """Test that the channels table and channel_id columns exist."""

    def test_channels_table_exists(self):
        with get_db() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "channels" in tables

    def test_channels_table_columns(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(channels)").fetchall()]
        expected = [
            "id", "workspace_id", "phone_number_id", "waba_id",
            "access_token", "display_name", "persona_prompt",
            "default_reply_mode", "kb_scope", "is_primary", "is_active",
            "created_at", "updated_at",
        ]
        for col in expected:
            assert col in cols, f"Missing column: {col}"

    def test_channel_id_added_to_contacts(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_messages(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_handoff_states(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(handoff_states)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_optouts(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(optouts)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_reply_modes(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reply_modes)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_campaigns(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(campaigns)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_added_to_assignments(self):
        with get_db() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(assignments)").fetchall()]
        assert "channel_id" in cols

    def test_channel_id_default_value(self):
        """channel_id should default to 'default' for backward compatibility."""
        with get_db() as conn:
            # Insert a contact without specifying channel_id
            conn.execute(
                "INSERT INTO contacts (id, workspace_id, phone, name, created_at) "
                "VALUES ('test1', 'default', '+1234567890', 'Test', '2025-01-01')"
            )
            row = conn.execute(
                "SELECT channel_id FROM contacts WHERE id = 'test1'"
            ).fetchone()
        assert row[0] == "default"


# ──────────────────────────────────────────────────────────────────────────────
# channel.py — CRUD tests
# ──────────────────────────────────────────────────────────────────────────────

class TestChannelCreate:
    """Test channel creation."""

    def test_create_channel(self):
        ch = create_channel(
            phone_number_id="123456789",
            access_token="tok_abc",
            display_name="Sales",
        )
        assert ch["phone_number_id"] == "123456789"
        assert ch["display_name"] == "Sales"
        assert ch["access_token"] == "tok_abc"
        assert ch["workspace_id"] == "default"
        assert ch["is_active"] == 1
        assert ch["default_reply_mode"] == "auto_ai"
        assert ch["id"].startswith("ch_")

    def test_create_channel_with_all_fields(self):
        ch = create_channel(
            phone_number_id="999888777",
            access_token="tok_full",
            display_name="Support",
            waba_id="waba_123",
            persona_prompt="You are a support agent.",
            default_reply_mode="human_only",
            kb_scope="channel_custom",
            is_primary=True,
        )
        assert ch["waba_id"] == "waba_123"
        assert ch["persona_prompt"] == "You are a support agent."
        assert ch["default_reply_mode"] == "human_only"
        assert ch["kb_scope"] == "channel_custom"
        assert ch["is_primary"] == 1

    def test_create_duplicate_phone_number_id_raises(self):
        create_channel(phone_number_id="dup_phone", access_token="tok1")
        with pytest.raises(ValueError, match="already registered"):
            create_channel(phone_number_id="dup_phone", access_token="tok2")

    def test_create_channel_invalid_reply_mode(self):
        with pytest.raises(ValueError, match="Invalid reply mode"):
            create_channel(
                phone_number_id="inv_mode",
                access_token="tok",
                default_reply_mode="invalid",
            )

    def test_create_primary_unsets_others(self):
        ch1 = create_channel(
            phone_number_id="phone_1", access_token="tok1", is_primary=True,
        )
        ch2 = create_channel(
            phone_number_id="phone_2", access_token="tok2", is_primary=True,
        )
        # ch1 should no longer be primary
        refreshed = get_channel(ch1["id"])
        assert refreshed["is_primary"] == 0
        # ch2 should be primary
        refreshed2 = get_channel(ch2["id"])
        assert refreshed2["is_primary"] == 1


class TestChannelGet:
    """Test channel retrieval."""

    def test_get_channel_by_id(self):
        ch = create_channel(phone_number_id="get_test", access_token="tok")
        result = get_channel(ch["id"])
        assert result is not None
        assert result["id"] == ch["id"]
        assert result["phone_number_id"] == "get_test"

    def test_get_channel_nonexistent(self):
        result = get_channel("ch_nonexistent")
        assert result is None

    def test_get_channel_by_phone_number_id(self):
        create_channel(phone_number_id="lookup_phone", access_token="tok")
        result = get_channel_by_phone_number_id("lookup_phone")
        assert result is not None
        assert result["phone_number_id"] == "lookup_phone"

    def test_get_channel_by_phone_number_id_inactive(self):
        ch = create_channel(phone_number_id="inactive_phone", access_token="tok")
        delete_channel(ch["id"])  # soft-delete
        result = get_channel_by_phone_number_id("inactive_phone")
        assert result is None  # inactive channels not returned

    def test_get_channel_wrong_workspace(self):
        ch = create_channel(
            phone_number_id="ws_test", access_token="tok",
            workspace_id="workspace_a",
        )
        # Try to get from default workspace
        result = get_channel(ch["id"], workspace_id="default")
        assert result is None


class TestChannelList:
    """Test listing channels."""

    def test_list_channels_empty(self):
        result = list_channels()
        assert result == []

    def test_list_channels(self):
        create_channel(phone_number_id="list_1", access_token="tok1")
        create_channel(phone_number_id="list_2", access_token="tok2")
        result = list_channels()
        assert len(result) == 2

    def test_list_channels_excludes_inactive(self):
        ch1 = create_channel(phone_number_id="active_ch", access_token="tok1")
        ch2 = create_channel(phone_number_id="inactive_ch", access_token="tok2")
        delete_channel(ch2["id"])  # soft-delete
        result = list_channels()
        assert len(result) == 1
        assert result[0]["id"] == ch1["id"]

    def test_list_channels_include_inactive(self):
        create_channel(phone_number_id="a_ch", access_token="tok1")
        ch2 = create_channel(phone_number_id="i_ch", access_token="tok2")
        delete_channel(ch2["id"])
        result = list_channels(include_inactive=True)
        assert len(result) == 2

    def test_list_channels_workspace_scoped(self):
        create_channel(phone_number_id="ws_a_ph", access_token="tok", workspace_id="ws_a")
        create_channel(phone_number_id="ws_b_ph", access_token="tok", workspace_id="ws_b")
        result_a = list_channels(workspace_id="ws_a")
        result_b = list_channels(workspace_id="ws_b")
        assert len(result_a) == 1
        assert len(result_b) == 1

    def test_list_channels_primary_first(self):
        create_channel(phone_number_id="non_primary", access_token="tok1")
        create_channel(phone_number_id="primary_ch", access_token="tok2", is_primary=True)
        result = list_channels()
        assert result[0]["is_primary"] == 1


class TestChannelUpdate:
    """Test channel updates."""

    def test_update_display_name(self):
        ch = create_channel(phone_number_id="upd_test", access_token="tok")
        updated = update_channel(ch["id"], {"display_name": "New Name"})
        assert updated["display_name"] == "New Name"

    def test_update_persona_prompt(self):
        ch = create_channel(phone_number_id="persona_test", access_token="tok")
        updated = update_channel(ch["id"], {"persona_prompt": "You are friendly."})
        assert updated["persona_prompt"] == "You are friendly."

    def test_update_reply_mode(self):
        ch = create_channel(phone_number_id="mode_test", access_token="tok")
        updated = update_channel(ch["id"], {"default_reply_mode": "ai_draft"})
        assert updated["default_reply_mode"] == "ai_draft"

    def test_update_invalid_reply_mode(self):
        ch = create_channel(phone_number_id="inv_upd", access_token="tok")
        with pytest.raises(ValueError, match="Invalid reply mode"):
            update_channel(ch["id"], {"default_reply_mode": "bad_mode"})

    def test_update_nonexistent_channel(self):
        result = update_channel("ch_nonexistent", {"display_name": "X"})
        assert result is None

    def test_update_sets_primary(self):
        ch1 = create_channel(phone_number_id="p1", access_token="t1", is_primary=True)
        ch2 = create_channel(phone_number_id="p2", access_token="t2")
        update_channel(ch2["id"], {"is_primary": True})
        refreshed1 = get_channel(ch1["id"])
        refreshed2 = get_channel(ch2["id"])
        assert refreshed1["is_primary"] == 0
        assert refreshed2["is_primary"] == 1

    def test_update_ignores_unknown_fields(self):
        ch = create_channel(phone_number_id="ignore_test", access_token="tok")
        updated = update_channel(ch["id"], {"unknown_field": "value"})
        assert updated is not None  # no error, field just ignored


class TestChannelDelete:
    """Test channel deletion."""

    def test_soft_delete(self):
        ch = create_channel(phone_number_id="soft_del", access_token="tok")
        result = delete_channel(ch["id"])
        assert result is True
        # Channel still exists but inactive
        refreshed = get_channel(ch["id"])
        assert refreshed["is_active"] == 0

    def test_hard_delete(self):
        ch = create_channel(phone_number_id="hard_del", access_token="tok")
        result = delete_channel(ch["id"], hard=True)
        assert result is True
        refreshed = get_channel(ch["id"])
        assert refreshed is None

    def test_delete_nonexistent(self):
        result = delete_channel("ch_nonexistent")
        assert result is False


class TestChannelHelpers:
    """Test helper functions."""

    def test_get_primary_channel(self):
        create_channel(phone_number_id="non_p", access_token="tok1")
        create_channel(phone_number_id="primary_h", access_token="tok2", is_primary=True)
        primary = get_primary_channel()
        assert primary is not None
        assert primary["phone_number_id"] == "primary_h"

    def test_get_primary_channel_none(self):
        create_channel(phone_number_id="no_primary", access_token="tok")
        primary = get_primary_channel()
        assert primary is None  # none marked as primary

    def test_get_channel_config(self):
        ch = create_channel(
            phone_number_id="cfg_test", access_token="tok",
            display_name="Config Test",
            persona_prompt="Be helpful.",
            default_reply_mode="ai_draft",
            kb_scope="channel_custom",
        )
        cfg = get_channel_config(ch["id"])
        assert cfg is not None
        assert cfg["display_name"] == "Config Test"
        assert cfg["persona_prompt"] == "Be helpful."
        assert cfg["default_reply_mode"] == "ai_draft"
        assert cfg["kb_scope"] == "channel_custom"
        assert "access_token" not in cfg  # credentials not in config

    def test_get_channel_config_nonexistent(self):
        cfg = get_channel_config("ch_nonexistent")
        assert cfg is None

    def test_get_channel_credentials(self):
        ch = create_channel(
            phone_number_id="cred_test", access_token="secret_token",
            waba_id="waba_xyz",
        )
        creds = get_channel_credentials(ch["id"])
        assert creds is not None
        assert creds["phone_number_id"] == "cred_test"
        assert creds["access_token"] == "secret_token"
        assert creds["waba_id"] == "waba_xyz"

    def test_get_channel_credentials_inactive(self):
        ch = create_channel(phone_number_id="cred_inactive", access_token="tok")
        delete_channel(ch["id"])
        creds = get_channel_credentials(ch["id"])
        assert creds is None  # inactive channels have no credentials

    def test_channel_count(self):
        assert channel_count() == 0
        create_channel(phone_number_id="cnt_1", access_token="tok1")
        assert channel_count() == 1
        ch2 = create_channel(phone_number_id="cnt_2", access_token="tok2")
        assert channel_count() == 2
        delete_channel(ch2["id"])  # soft-delete
        assert channel_count() == 1


class TestEnsureDefaultChannel:
    """Test the backward-compatibility default channel creation."""

    def test_ensure_default_creates(self):
        ch = ensure_default_channel(
            phone_number_id="env_phone_id",
            access_token="env_access_token",
        )
        assert ch["id"] == DEFAULT_CHANNEL
        assert ch["phone_number_id"] == "env_phone_id"
        assert ch["is_primary"] == 1

    def test_ensure_default_idempotent(self):
        ch1 = ensure_default_channel(
            phone_number_id="env_phone_id", access_token="tok1",
        )
        ch2 = ensure_default_channel(
            phone_number_id="env_phone_id", access_token="tok2",
        )
        # Should return the same channel, not create a new one
        assert ch2["phone_number_id"] == "env_phone_id"

    def test_ensure_default_does_not_duplicate(self):
        ensure_default_channel(phone_number_id="unique_ph", access_token="tok")
        # Count channels
        count = channel_count()
        assert count == 1


# ──────────────────────────────────────────────────────────────────────────────
# schemas.py — Channel validation tests
# ──────────────────────────────────────────────────────────────────────────────

class TestChannelSchemas:
    """Test Pydantic schema validation for channels."""

    def test_create_channel_request_valid(self):
        from schemas import CreateChannelRequest
        req = CreateChannelRequest(
            phone_number_id="12345",
            access_token="tok_abc",
            display_name="Sales",
        )
        assert req.phone_number_id == "12345"
        assert req.default_reply_mode == "auto_ai"

    def test_create_channel_request_missing_required(self):
        from schemas import CreateChannelRequest
        with pytest.raises(Exception):
            CreateChannelRequest(display_name="No Phone")

    def test_create_channel_request_invalid_mode(self):
        from schemas import CreateChannelRequest
        with pytest.raises(Exception):
            CreateChannelRequest(
                phone_number_id="12345",
                access_token="tok",
                default_reply_mode="bad_mode",
            )

    def test_create_channel_request_empty_phone(self):
        from schemas import CreateChannelRequest
        with pytest.raises(Exception):
            CreateChannelRequest(
                phone_number_id="   ",
                access_token="tok",
            )

    def test_update_channel_request_partial(self):
        from schemas import UpdateChannelRequest
        req = UpdateChannelRequest(display_name="New Name")
        assert req.display_name == "New Name"
        assert req.persona_prompt is None
        assert req.default_reply_mode is None

    def test_update_channel_request_invalid_mode(self):
        from schemas import UpdateChannelRequest
        with pytest.raises(Exception):
            UpdateChannelRequest(default_reply_mode="nonsense")

    def test_update_channel_request_valid_mode(self):
        from schemas import UpdateChannelRequest
        req = UpdateChannelRequest(default_reply_mode="human_only")
        assert req.default_reply_mode == "human_only"
