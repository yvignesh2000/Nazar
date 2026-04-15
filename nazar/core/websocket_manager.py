# -*- coding: utf-8 -*-
"""
Nazar — WebSocket Connection Manager

Provides real-time push events to the dashboard so it doesn't need to poll.

Events emitted:
  new_message         — inbound message received from customer
  ai_reply            — bot sent a reply
  handoff_triggered   — contact moved to human mode
  bot_resumed         — contact moved back to bot mode
  draft_ready         — new AI draft waiting for human review
  contact_updated     — contact profile changed (stage, score, etc.)
  campaign_progress   — live campaign send progress
  typing_indicator    — bot is "thinking" (sent before AI responds)

Connection lifecycle:
  - Client connects to /ws?token=<jwt>  (or /ws?key=<api_key> for dev)
  - Server validates auth, registers connection
  - Server pushes events as JSON lines
  - Client disconnects → connection removed silently

Usage (from server.py):
  from websocket_manager import ws_manager
  await ws_manager.broadcast({"type": "new_message", "contact_id": "...", ...})
  await ws_manager.send_to_workspace("ws_abc", {...})
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Set, Dict

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))


class WebSocketManager:
    """Manages all active WebSocket connections across workspaces."""

    def __init__(self):
        # workspace_id -> set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket -> workspace_id (reverse lookup for cleanup)
        self._ws_to_workspace: Dict[WebSocket, str] = {}

    def _now(self) -> str:
        return datetime.now(IST).isoformat()

    async def connect(self, websocket: WebSocket, workspace_id: str):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        if workspace_id not in self._connections:
            self._connections[workspace_id] = set()
        self._connections[workspace_id].add(websocket)
        self._ws_to_workspace[websocket] = workspace_id
        logger.info(
            f"WebSocket connected: workspace={workspace_id} "
            f"total={len(self._connections[workspace_id])}"
        )

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        workspace_id = self._ws_to_workspace.pop(websocket, None)
        if workspace_id and workspace_id in self._connections:
            self._connections[workspace_id].discard(websocket)
            if not self._connections[workspace_id]:
                del self._connections[workspace_id]
            logger.info(f"WebSocket disconnected: workspace={workspace_id}")

    async def send_to_workspace(self, workspace_id: str, event: dict):
        """
        Send an event to all connections in a workspace.
        Dead connections are removed silently.
        """
        if workspace_id not in self._connections:
            return

        message = json.dumps({**event, "ts": self._now()})
        dead = set()

        for ws in list(self._connections[workspace_id]):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        # Clean up dead connections
        for ws in dead:
            self.disconnect(ws)

    async def broadcast(self, event: dict):
        """Broadcast an event to ALL connected workspaces."""
        for workspace_id in list(self._connections.keys()):
            await self.send_to_workspace(workspace_id, event)

    def connection_count(self, workspace_id: str = None) -> int:
        """Count active connections, optionally filtered by workspace."""
        if workspace_id:
            return len(self._connections.get(workspace_id, set()))
        return sum(len(conns) for conns in self._connections.values())

    async def send_typing_indicator(self, workspace_id: str, contact_id: str):
        """Send a typing indicator (bot is generating a reply)."""
        await self.send_to_workspace(workspace_id, {
            "type": "typing_indicator",
            "contact_id": contact_id,
        })

    async def send_new_message(
        self,
        workspace_id: str,
        contact_id: str,
        contact_name: str,
        direction: str,
        content: str,
        sent_by: str = "bot",
    ):
        """Notify dashboard of a new inbound or outbound message."""
        await self.send_to_workspace(workspace_id, {
            "type": "new_message",
            "contact_id": contact_id,
            "contact_name": contact_name,
            "direction": direction,
            "content": content[:500],
            "sent_by": sent_by,
        })

    async def send_handoff_event(
        self,
        workspace_id: str,
        contact_id: str,
        contact_name: str,
        reason: str,
        triggered: bool = True,
    ):
        """Notify dashboard of a handoff trigger or bot resume."""
        await self.send_to_workspace(workspace_id, {
            "type": "handoff_triggered" if triggered else "bot_resumed",
            "contact_id": contact_id,
            "contact_name": contact_name,
            "reason": reason,
        })

    async def send_draft_ready(
        self,
        workspace_id: str,
        contact_id: str,
        contact_name: str,
        draft_preview: str,
    ):
        """Notify dashboard that a new AI draft is ready for review."""
        await self.send_to_workspace(workspace_id, {
            "type": "draft_ready",
            "contact_id": contact_id,
            "contact_name": contact_name,
            "draft_preview": draft_preview[:200],
        })

    async def send_contact_updated(
        self,
        workspace_id: str,
        contact_id: str,
        fields: dict,
    ):
        """Notify dashboard of a contact profile update."""
        await self.send_to_workspace(workspace_id, {
            "type": "contact_updated",
            "contact_id": contact_id,
            "fields": fields,
        })

    async def send_campaign_progress(
        self,
        workspace_id: str,
        campaign_id: str,
        sent: int,
        total: int,
        failed: int = 0,
        status: str = "sending",
    ):
        """Send live campaign progress update."""
        await self.send_to_workspace(workspace_id, {
            "type": "campaign_progress",
            "campaign_id": campaign_id,
            "sent": sent,
            "total": total,
            "failed": failed,
            "pct": round(sent / max(total, 1) * 100, 1),
            "status": status,
        })

    async def ping_all(self):
        """Send a keepalive ping to all connections."""
        dead = []
        for workspace_id, connections in list(self._connections.items()):
            for ws in list(connections):
                try:
                    await ws.send_text(json.dumps({"type": "ping", "ts": self._now()}))
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Global singleton — import this everywhere
ws_manager = WebSocketManager()
