"""
Tests for session token revocation (Plan item #18).
"""

import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))


@pytest.fixture(autouse=True)
def clean_revocation_state(tmp_path, monkeypatch):
    """
    Reset the revocation state and use a temp file for each test.
    """
    import auth_manager
    # Clear revoked tokens set
    auth_manager._revoked_tokens.clear()
    # Point revocation file to temp dir
    monkeypatch.setattr(auth_manager, "_REVOKED_PATH", tmp_path / ".revoked_tokens.json")
    yield
    auth_manager._revoked_tokens.clear()


class TestTokenRevocation:
    def _get_valid_token(self, tmp_path):
        """Bootstrap a workspace and get a valid token."""
        import auth_manager

        # Point data dirs to temp
        data_dir = tmp_path / "auth"
        data_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(auth_manager, "DATA_DIR", data_dir):
            ws = auth_manager.create_workspace("Test WS", "test@example.com")
            ws_id = ws["workspace_id"]
            # Create user
            user = auth_manager.create_user("test@example.com", "password123", ws_id, "admin")
            token = auth_manager.login("test@example.com", "password123", ws_id)
            return token, ws_id, data_dir

    def test_is_token_revoked_false_by_default(self):
        import auth_manager
        assert auth_manager.is_token_revoked("some_token") is False

    def test_revoke_token_marks_it_revoked(self):
        import auth_manager
        token = "fake_token_xyz"
        auth_manager.revoke_token(token)
        assert auth_manager.is_token_revoked(token) is True

    def test_revoke_token_persists_to_file(self, tmp_path):
        import auth_manager
        token = "persist_test_token"
        auth_manager.revoke_token(token)
        revoked_path = tmp_path / ".revoked_tokens.json"
        assert revoked_path.exists()

    def test_multiple_tokens_can_be_revoked(self):
        import auth_manager
        auth_manager.revoke_token("token_a")
        auth_manager.revoke_token("token_b")
        assert auth_manager.is_token_revoked("token_a") is True
        assert auth_manager.is_token_revoked("token_b") is True
        assert auth_manager.is_token_revoked("token_c") is False

    def test_non_revoked_token_not_in_set(self):
        import auth_manager
        auth_manager.revoke_token("revoked_one")
        assert auth_manager.is_token_revoked("not_revoked_one") is False

    def test_validate_token_returns_none_for_revoked(self, tmp_path):
        """A revoked valid token should fail validation."""
        import auth_manager

        # We need a syntactically valid token to test this
        # Use _make_token directly
        data_dir = tmp_path / "auth"
        data_dir.mkdir(parents=True, exist_ok=True)
        with patch.object(auth_manager, "DATA_DIR", data_dir):
            ws = auth_manager.create_workspace("TestWS2", "user2@example.com")
            ws_id = ws["workspace_id"]
            user = auth_manager.create_user("user2@example.com", "pass1234", ws_id)
            token = auth_manager.login("user2@example.com", "pass1234", ws_id)
            assert token is not None

            # Before revoking — should be valid
            ctx = auth_manager.validate_token(token)
            assert ctx is not None

            # Revoke it
            auth_manager.revoke_token(token)

            # After revoking — should return None
            ctx_after = auth_manager.validate_token(token)
            assert ctx_after is None
