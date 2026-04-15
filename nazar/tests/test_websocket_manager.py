"""
Unit tests for core/websocket_manager.py

Tests: connection management, broadcast, workspace isolation,
       event helper methods, dead connection cleanup.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWebSocketManagerConnectionCount:
    def test_starts_empty(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        assert mgr.connection_count() == 0

    @pytest.mark.asyncio
    async def test_connect_increments_count(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")
        assert mgr.connection_count("ws_abc") == 1

    @pytest.mark.asyncio
    async def test_disconnect_decrements_count(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")
        mgr.disconnect(ws)
        assert mgr.connection_count("ws_abc") == 0

    @pytest.mark.asyncio
    async def test_multiple_workspaces(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1, "ws_aaa")
        await mgr.connect(ws2, "ws_bbb")
        assert mgr.connection_count("ws_aaa") == 1
        assert mgr.connection_count("ws_bbb") == 1
        assert mgr.connection_count() == 2

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ws_safe(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        # Should not raise
        mgr.disconnect(ws)


class TestWebSocketBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_workspaces(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1, "ws_aaa")
        await mgr.connect(ws2, "ws_bbb")

        await mgr.broadcast({"type": "ping"})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_to_workspace_only_targets_correct_ws(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect(ws1, "ws_aaa")
        await mgr.connect(ws2, "ws_bbb")

        await mgr.send_to_workspace("ws_aaa", {"type": "test"})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_to_empty_workspace_safe(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        # Should not raise
        await mgr.send_to_workspace("ws_nonexistent", {"type": "ping"})

    @pytest.mark.asyncio
    async def test_dead_connections_cleaned_up(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()

        ws = AsyncMock()
        ws.send_text.side_effect = Exception("Connection closed")
        await mgr.connect(ws, "ws_abc")

        await mgr.send_to_workspace("ws_abc", {"type": "ping"})

        # Dead connection should be removed
        assert mgr.connection_count("ws_abc") == 0

    @pytest.mark.asyncio
    async def test_broadcast_event_contains_timestamp(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.broadcast({"type": "test_event"})

        call_args = ws.send_text.call_args[0][0]
        event = json.loads(call_args)
        assert "ts" in event
        assert event["type"] == "test_event"


class TestWebSocketHelperMethods:
    @pytest.mark.asyncio
    async def test_send_new_message(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.send_new_message("ws_abc", "c1", "Alice", "inbound", "Hello!")

        call_args = json.loads(ws.send_text.call_args[0][0])
        assert call_args["type"] == "new_message"
        assert call_args["contact_id"] == "c1"
        assert call_args["direction"] == "inbound"

    @pytest.mark.asyncio
    async def test_send_handoff_event(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.send_handoff_event("ws_abc", "c1", "Alice", "Customer frustrated")

        call_args = json.loads(ws.send_text.call_args[0][0])
        assert call_args["type"] == "handoff_triggered"
        assert call_args["reason"] == "Customer frustrated"

    @pytest.mark.asyncio
    async def test_send_draft_ready(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.send_draft_ready("ws_abc", "c1", "Alice", "Here is the draft reply...")

        call_args = json.loads(ws.send_text.call_args[0][0])
        assert call_args["type"] == "draft_ready"
        assert "draft_preview" in call_args

    @pytest.mark.asyncio
    async def test_send_campaign_progress(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.send_campaign_progress("ws_abc", "cmp_123", 50, 100, failed=2)

        call_args = json.loads(ws.send_text.call_args[0][0])
        assert call_args["type"] == "campaign_progress"
        assert call_args["sent"] == 50
        assert call_args["total"] == 100
        assert call_args["pct"] == 50.0

    @pytest.mark.asyncio
    async def test_send_contact_updated(self):
        from websocket_manager import WebSocketManager
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws, "ws_abc")

        await mgr.send_contact_updated("ws_abc", "c1", {"pipeline_stage": "Qualified"})

        call_args = json.loads(ws.send_text.call_args[0][0])
        assert call_args["type"] == "contact_updated"
        assert call_args["fields"]["pipeline_stage"] == "Qualified"
