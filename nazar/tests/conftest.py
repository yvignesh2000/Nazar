"""
Nazar — Test Configuration & Shared Fixtures

Provides:
- Isolated temp data directories per test
- FastAPI test client
- Seeded contacts and conversations
- Mock LLM responses
"""

import json
import os
import shutil
import sys
import pytest
import pytest_asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Ensure the project root and core are on the path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

# Set test env vars before any imports
os.environ.setdefault("NAZAR_API_KEY", "test_key_abc123")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-v1-test")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")


@pytest.fixture(scope="function")
def tmp_data_dir(tmp_path, monkeypatch):
    """
    Provide a fresh, isolated data directory for each test.
    Patches DATA_DIR in all modules that use it.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Patch DATA_DIR in each module
    import contact_manager
    import customer_memory
    import handoff_manager
    import auth_manager
    import billing
    import onboarding
    import analytics
    import usage_tracker
    import template_manager

    monkeypatch.setattr(contact_manager, "DATA_DIR", data_dir / "contacts")
    monkeypatch.setattr(customer_memory, "DATA_DIR", data_dir / "contacts")
    monkeypatch.setattr(handoff_manager, "DATA_DIR", data_dir / "handoffs")
    monkeypatch.setattr(auth_manager, "DATA_DIR", data_dir / "auth")
    monkeypatch.setattr(billing, "DATA_DIR", data_dir / "billing")
    monkeypatch.setattr(onboarding, "DATA_DIR", data_dir / "onboarding")
    monkeypatch.setattr(analytics, "DATA_DIR", data_dir / "analytics")
    monkeypatch.setattr(usage_tracker, "DATA_DIR", data_dir / "usage")
    monkeypatch.setattr(template_manager, "DATA_DIR", data_dir)

    # Create subdirectories
    (data_dir / "contacts").mkdir()
    (data_dir / "handoffs").mkdir()
    (data_dir / "auth").mkdir()
    (data_dir / "billing").mkdir()
    (data_dir / "onboarding").mkdir()
    (data_dir / "analytics").mkdir()
    (data_dir / "usage").mkdir()

    # Reset template_manager's module-level cache so it doesn't read stale templates.json
    template_manager._load_templates.cache_clear() if hasattr(template_manager._load_templates, 'cache_clear') else None

    yield data_dir


@pytest.fixture
def sample_contact(tmp_data_dir):
    """Create a sample contact for tests."""
    from contact_manager import create_contact
    return create_contact(
        name="Test User",
        phone="+919876543210",
        company="TestCo",
        source="test",
        tags=["enterprise"],
    )


@pytest.fixture
def sample_contact_2(tmp_data_dir):
    """Create a second sample contact."""
    from contact_manager import create_contact
    return create_contact(
        name="Jane Doe",
        phone="+919876543211",
        company="Jane Corp",
        source="referral",
        tags=["sme"],
    )


@pytest.fixture
def mock_llm():
    """Patch call_llm_safe to return a canned response."""
    with patch("llm_router.call_llm_safe", new_callable=AsyncMock) as mock:
        mock.return_value = "This is a test AI response."
        yield mock


@pytest.fixture
def mock_llm_handoff():
    """Patch call_llm_safe to return a handoff-triggering JSON."""
    with patch("llm_router.call_llm_safe", new_callable=AsyncMock) as mock:
        mock.return_value = json.dumps({
            "handoff": True,
            "reason": "Customer frustrated",
            "confidence": 0.95,
            "category": "frustration",
        })
        yield mock


@pytest.fixture
def sample_workspace(tmp_data_dir):
    """Create a sample workspace and owner."""
    from auth_manager import create_workspace, create_user
    ws = create_workspace("Test Biz", "owner@test.com", plan="growth")
    user = create_user("owner@test.com", "Test123!", ws["workspace_id"], role="owner", name="Owner")
    return {"workspace": ws, "user": user}


@pytest.fixture
def sample_subscription(tmp_data_dir, sample_workspace):
    """Create an active subscription for the sample workspace."""
    from billing import create_subscription
    ws_id = sample_workspace["workspace"]["workspace_id"]
    return create_subscription(ws_id, "growth", trial=True)


# ---------------------------------------------------------------------------
# FastAPI test client (async)
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client(tmp_data_dir, monkeypatch, tmp_path):
    """
    Provide a FastAPI test client with mocked data paths and LLM.
    """
    from fastapi.testclient import TestClient

    # Patch knowledge base and config paths in server module context
    kb_file = tmp_path / "knowledge_base.txt"
    kb_file.write_text("Test product info: Nazar is a WhatsApp sales tool.")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "business_name": "Test Biz",
        "bot_enabled": True,
        "smart_handoff": True,
    }))

    import server
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "API_KEY", "test_key_abc123")

    with patch("llm_router.call_llm_safe", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Hello! This is a test AI response."

        client = TestClient(server.app, raise_server_exceptions=False)
        client.mock_llm = mock_llm
        yield client


@pytest.fixture
def auth_headers():
    """Return headers for authenticated requests."""
    return {"X-Nazar-Key": "test_key_abc123"}
