# -*- coding: utf-8 -*-
"""
Nazar — Workspace & Channel Context (Multi-Tenancy + Multi-Channel)

Provides thread-local workspace and channel scoping for all database
operations.  Instead of passing workspace_id / channel_id through every
function call, the server sets the context once per request, and all DB
queries automatically scope to the correct workspace **and** channel.

Usage in server.py (middleware):
    from workspace_context import set_workspace, set_channel

    # In auth middleware or per-route:
    set_workspace(ctx["workspace_id"])

    # In webhook handler — after looking up the channel from phone_number_id:
    set_channel(channel_id)

Usage in core modules:
    from workspace_context import get_workspace, get_channel

    def list_contacts(...):
        ws = get_workspace()
        ch = get_channel()
        # Use ws + ch in queries

This pattern:
  - Maintains backward compatibility (defaults to 'default')
  - Requires zero changes to function signatures
  - Works with thread-local connections (matches SQLite approach)
"""

import threading

_context = threading.local()

DEFAULT_WORKSPACE = "default"
DEFAULT_CHANNEL = "default"


# ──────────────────────────────────────────────────────────────────────────────
# Workspace context
# ──────────────────────────────────────────────────────────────────────────────

def set_workspace(workspace_id: str):
    """Set the workspace ID for the current thread/request."""
    _context.workspace_id = workspace_id


def get_workspace() -> str:
    """Get the current workspace ID. Returns 'default' if not set."""
    return getattr(_context, "workspace_id", DEFAULT_WORKSPACE)


def clear_workspace():
    """Clear the workspace context (call on request cleanup)."""
    _context.workspace_id = DEFAULT_WORKSPACE


# ──────────────────────────────────────────────────────────────────────────────
# Channel context
# ──────────────────────────────────────────────────────────────────────────────

def set_channel(channel_id: str):
    """Set the channel ID for the current thread/request."""
    _context.channel_id = channel_id


def get_channel() -> str:
    """Get the current channel ID. Returns 'default' if not set."""
    return getattr(_context, "channel_id", DEFAULT_CHANNEL)


def clear_channel():
    """Clear the channel context (call on request cleanup)."""
    _context.channel_id = DEFAULT_CHANNEL


# ──────────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────────

def clear_context():
    """Clear both workspace and channel context."""
    clear_workspace()
    clear_channel()
