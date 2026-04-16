# -*- coding: utf-8 -*-
"""
Nazar — Workspace Context (Multi-Tenancy)

Provides thread-local workspace scoping for all database operations.
Instead of passing workspace_id through every function call, the server
sets the workspace context once per request, and all DB queries
automatically scope to that workspace.

Usage in server.py (middleware):
    from workspace_context import set_workspace, get_workspace

    # In your auth middleware or per-route:
    set_workspace(ctx["workspace_id"])

Usage in core modules:
    from workspace_context import get_workspace

    def list_contacts(...):
        ws = get_workspace()
        # Use ws in queries

This pattern:
  - Maintains backward compatibility (defaults to 'default')
  - Requires zero changes to function signatures
  - Works with thread-local connections (matches SQLite approach)
"""

import threading

_context = threading.local()

DEFAULT_WORKSPACE = "default"


def set_workspace(workspace_id: str):
    """Set the workspace ID for the current thread/request."""
    _context.workspace_id = workspace_id


def get_workspace() -> str:
    """Get the current workspace ID. Returns 'default' if not set."""
    return getattr(_context, "workspace_id", DEFAULT_WORKSPACE)


def clear_workspace():
    """Clear the workspace context (call on request cleanup)."""
    _context.workspace_id = DEFAULT_WORKSPACE
