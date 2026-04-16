"""
Tests for core/webhook_dispatcher.py — outbound webhook dispatcher.
"""

import asyncio
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
import webhook_dispatcher as wd


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


class TestRegisterWebhook:
    def test_register_basic_webhook(self):
        hook = wd.register_webhook("https://example.com/hook")
        assert hook["id"].startswith("wh_")
        assert hook["url"] == "https://example.com/hook"
        assert hook["active"] is True

    def test_register_with_events(self):
        hook = wd.register_webhook("https://example.com/hook2", events=["message.inbound"])
        assert hook["events"] == ["message.inbound"]

    def test_register_with_secret(self):
        hook = wd.register_webhook("https://example.com/hook3", secret="mysecret")
        assert hook["secret"] == "mysecret"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="must start with"):
            wd.register_webhook("not_a_url")

    def test_webhook_persisted(self, tmp_path):
        hook = wd.register_webhook("https://example.com/hook4")
        hooks = wd.list_webhooks()
        ids = [h["id"] for h in hooks]
        assert hook["id"] in ids


class TestListWebhooks:
    def test_list_returns_all(self):
        wd.register_webhook("https://a.com/1")
        wd.register_webhook("https://b.com/2")
        hooks = wd.list_webhooks()
        assert len(hooks) >= 2

    def test_active_only_filter(self):
        h1 = wd.register_webhook("https://c.com/1")
        h2 = wd.register_webhook("https://d.com/2")
        wd.update_webhook(h2["id"], active=False)
        active = wd.list_webhooks(active_only=True)
        active_ids = [h["id"] for h in active]
        assert h1["id"] in active_ids
        assert h2["id"] not in active_ids


class TestUpdateWebhook:
    def test_update_url(self):
        hook = wd.register_webhook("https://orig.com/hook")
        updated = wd.update_webhook(hook["id"], url="https://new.com/hook")
        assert updated["url"] == "https://new.com/hook"

    def test_update_deactivate(self):
        hook = wd.register_webhook("https://active.com/hook")
        updated = wd.update_webhook(hook["id"], active=False)
        assert updated["active"] is False

    def test_update_nonexistent_raises(self):
        with pytest.raises(ValueError):
            wd.update_webhook("nonexistent_id", active=True)


class TestDeleteWebhook:
    def test_delete_removes_webhook(self):
        hook = wd.register_webhook("https://del.com/hook")
        deleted = wd.delete_webhook(hook["id"])
        assert deleted is True
        assert wd.get_webhook(hook["id"]) is None

    def test_delete_nonexistent_returns_false(self):
        assert wd.delete_webhook("no_such_id") is False


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_calls_registered_hooks(self):
        hook = wd.register_webhook("https://recv.com/hook", events=["message.inbound"])

        sent_payloads = []

        async def fake_send(h, event, payload, record_stats=True):
            sent_payloads.append((h["id"], event, payload))
            return True, 200, ""

        with patch.object(wd, "_send", fake_send):
            count = await wd.dispatch("message.inbound", {"contact_id": "c_1"})
            await asyncio.sleep(0.05)  # Let background tasks run

        assert count >= 1
        assert any(p[0] == hook["id"] for p in sent_payloads)

    @pytest.mark.asyncio
    async def test_dispatch_skips_inactive_hooks(self):
        hook = wd.register_webhook("https://inactive.com/hook", events=["*"])
        wd.update_webhook(hook["id"], active=False)

        sent_payloads = []

        async def fake_send(h, event, payload, record_stats=True):
            sent_payloads.append(h["id"])
            return True, 200, ""

        with patch.object(wd, "_send", fake_send):
            await wd.dispatch("message.inbound", {})
            await asyncio.sleep(0.05)

        assert hook["id"] not in sent_payloads

    @pytest.mark.asyncio
    async def test_wildcard_event_matches_all(self):
        hook = wd.register_webhook("https://wild.com/hook", events=["*"])
        fired = []

        async def fake_send(h, event, payload, record_stats=True):
            fired.append(event)
            return True, 200, ""

        with patch.object(wd, "_send", fake_send):
            await wd.dispatch("contact.created", {"contact_id": "c_2"})
            await asyncio.sleep(0.05)  # Let background tasks run

        assert "contact.created" in fired


class TestDispatchTest:
    @pytest.mark.asyncio
    async def test_dispatch_test_returns_result(self):
        hook = wd.register_webhook("https://test.com/hook")

        async def fake_send(h, event, payload, record_stats=True):
            return True, 200, ""

        with patch.object(wd, "_send", fake_send):
            result = await wd.dispatch_test(hook["id"])

        assert result["ok"] is True
        assert result["webhook_id"] == hook["id"]

    @pytest.mark.asyncio
    async def test_dispatch_test_nonexistent_raises(self):
        with pytest.raises(ValueError):
            await wd.dispatch_test("no_such_hook")
