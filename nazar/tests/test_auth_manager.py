"""
Unit tests for core/auth_manager.py

Tests: workspace CRUD, user CRUD, authentication, permissions,
       invitations, API key validation, token lifecycle.
"""

import pytest
import time


class TestWorkspace:
    def test_create_workspace(self, tmp_data_dir):
        from auth_manager import create_workspace
        ws = create_workspace("My Biz", "owner@biz.com", plan="starter")
        assert ws["workspace_id"].startswith("ws_")
        assert ws["api_key"].startswith("nzr_")
        assert ws["name"] == "My Biz"
        assert ws["plan"] == "starter"

    def test_get_workspace(self, tmp_data_dir, sample_workspace):
        from auth_manager import get_workspace
        ws = get_workspace(sample_workspace["workspace"]["workspace_id"])
        assert ws is not None
        assert ws["name"] == "Test Biz"

    def test_get_workspace_not_found(self, tmp_data_dir):
        from auth_manager import get_workspace
        assert get_workspace("ws_nonexistent") is None

    def test_get_workspace_by_api_key(self, tmp_data_dir, sample_workspace):
        from auth_manager import get_workspace_by_api_key
        ws = sample_workspace["workspace"]
        found = get_workspace_by_api_key(ws["api_key"])
        assert found is not None
        assert found["workspace_id"] == ws["workspace_id"]

    def test_regenerate_api_key(self, tmp_data_dir, sample_workspace):
        from auth_manager import regenerate_api_key, get_workspace
        ws_id = sample_workspace["workspace"]["workspace_id"]
        old_key = sample_workspace["workspace"]["api_key"]
        new_key = regenerate_api_key(ws_id)
        assert new_key != old_key
        assert new_key.startswith("nzr_")
        ws = get_workspace(ws_id)
        assert ws["api_key"] == new_key


class TestUserCRUD:
    def test_create_user(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_user
        ws_id = sample_workspace["workspace"]["workspace_id"]
        user = create_user("agent@biz.com", "Pass123!", ws_id, role="agent", name="Agent")
        assert user["user_id"].startswith("usr_")
        assert user["email"] == "agent@biz.com"
        assert user["role"] == "agent"
        assert "password_hash" not in user

    def test_create_user_invalid_role(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_user
        ws_id = sample_workspace["workspace"]["workspace_id"]
        with pytest.raises(ValueError, match="Invalid role"):
            create_user("x@biz.com", "Pass123!", ws_id, role="superuser")

    def test_create_duplicate_user(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_user
        ws_id = sample_workspace["workspace"]["workspace_id"]
        # owner@test.com already created in sample_workspace fixture
        with pytest.raises(ValueError, match="already exists"):
            create_user("owner@test.com", "Pass123!", ws_id, role="agent")

    def test_get_user(self, tmp_data_dir, sample_workspace):
        from auth_manager import get_user
        user_id = sample_workspace["user"]["user_id"]
        user = get_user(user_id)
        assert user is not None
        assert user["email"] == "owner@test.com"

    def test_list_workspace_users(self, tmp_data_dir, sample_workspace):
        from auth_manager import list_workspace_users, create_user
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_user("agent2@test.com", "Pass123!", ws_id, role="agent")
        users = list_workspace_users(ws_id)
        assert len(users) >= 2

    def test_update_user(self, tmp_data_dir, sample_workspace):
        from auth_manager import update_user
        user_id = sample_workspace["user"]["user_id"]
        updated = update_user(user_id, name="New Name")
        assert updated["name"] == "New Name"

    def test_update_user_invalid_role(self, tmp_data_dir, sample_workspace):
        from auth_manager import update_user
        user_id = sample_workspace["user"]["user_id"]
        with pytest.raises(ValueError):
            update_user(user_id, role="superuser")

    def test_soft_delete_user(self, tmp_data_dir, sample_workspace):
        from auth_manager import delete_user, get_user
        user_id = sample_workspace["user"]["user_id"]
        delete_user(user_id)
        user = get_user(user_id)
        assert user["active"] is False


class TestAuthentication:
    def test_login_success(self, tmp_data_dir, sample_workspace):
        from auth_manager import login
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("owner@test.com", "Test123!", ws_id)
        assert token is not None
        assert ":" in token

    def test_login_wrong_password(self, tmp_data_dir, sample_workspace):
        from auth_manager import login
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("owner@test.com", "WrongPassword", ws_id)
        assert token is None

    def test_login_wrong_email(self, tmp_data_dir, sample_workspace):
        from auth_manager import login
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("nobody@test.com", "Test123!", ws_id)
        assert token is None

    def test_validate_token(self, tmp_data_dir, sample_workspace):
        from auth_manager import login, validate_token
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("owner@test.com", "Test123!", ws_id)
        ctx = validate_token(token)
        assert ctx is not None
        assert ctx["user"]["email"] == "owner@test.com"
        assert ctx["workspace"]["workspace_id"] == ws_id

    def test_invalid_token_rejected(self, tmp_data_dir):
        from auth_manager import validate_token
        assert validate_token("garbage.token.invalid") is None
        assert validate_token("") is None

    def test_tampered_token_rejected(self, tmp_data_dir, sample_workspace):
        from auth_manager import login, validate_token
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("owner@test.com", "Test123!", ws_id)
        # Tamper with the token
        tampered = token[:-4] + "XXXX"
        assert validate_token(tampered) is None

    def test_change_password(self, tmp_data_dir, sample_workspace):
        from auth_manager import change_password, login
        ws_id = sample_workspace["workspace"]["workspace_id"]
        user_id = sample_workspace["user"]["user_id"]
        ok = change_password(user_id, "Test123!", "NewPass456!")
        assert ok is True
        # Old password no longer works
        assert login("owner@test.com", "Test123!", ws_id) is None
        # New password works
        assert login("owner@test.com", "NewPass456!", ws_id) is not None

    def test_change_password_wrong_old(self, tmp_data_dir, sample_workspace):
        from auth_manager import change_password
        user_id = sample_workspace["user"]["user_id"]
        ok = change_password(user_id, "WrongOld", "NewPass456!")
        assert ok is False


class TestPermissions:
    def test_owner_has_all_permissions(self, tmp_data_dir, sample_workspace):
        from auth_manager import login, check_permission
        ws_id = sample_workspace["workspace"]["workspace_id"]
        token = login("owner@test.com", "Test123!", ws_id)
        for perm in ["read", "write", "send", "configure", "manage_users", "billing"]:
            assert check_permission(token, perm) is not None, f"Owner should have {perm}"

    def test_agent_limited_permissions(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_user, login, check_permission
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_user("agent@test.com", "Pass123!", ws_id, role="agent")
        token = login("agent@test.com", "Pass123!", ws_id)
        assert check_permission(token, "read") is not None
        assert check_permission(token, "send") is not None
        assert check_permission(token, "billing") is None
        assert check_permission(token, "configure") is None

    def test_viewer_read_only(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_user, login, check_permission
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_user("viewer@test.com", "Pass123!", ws_id, role="viewer")
        token = login("viewer@test.com", "Pass123!", ws_id)
        assert check_permission(token, "read") is not None
        assert check_permission(token, "send") is None
        assert check_permission(token, "write") is None


class TestInvitations:
    def test_create_invite(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_invite
        ws_id = sample_workspace["workspace"]["workspace_id"]
        invite = create_invite(ws_id, "new@test.com", "agent", "admin")
        assert invite["token"]
        assert invite["email"] == "new@test.com"
        assert invite["role"] == "agent"

    def test_cannot_invite_as_owner(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_invite
        ws_id = sample_workspace["workspace"]["workspace_id"]
        with pytest.raises(ValueError):
            create_invite(ws_id, "x@test.com", "owner", "admin")

    def test_accept_invite(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_invite, accept_invite, get_user_by_email
        ws_id = sample_workspace["workspace"]["workspace_id"]
        invite = create_invite(ws_id, "new@test.com", "admin", "admin")
        user = accept_invite(invite["token"], "New User", "Pass123!")
        assert user is not None
        assert user["email"] == "new@test.com"
        assert user["role"] == "admin"

    def test_cannot_accept_twice(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_invite, accept_invite
        ws_id = sample_workspace["workspace"]["workspace_id"]
        invite = create_invite(ws_id, "new2@test.com", "agent", "admin")
        accept_invite(invite["token"], "User", "Pass123!")
        result = accept_invite(invite["token"], "User2", "Pass456!")
        assert result is None

    def test_invalid_invite_token(self, tmp_data_dir):
        from auth_manager import accept_invite
        result = accept_invite("invalidtoken", "User", "Pass123!")
        assert result is None

    def test_list_pending_invites(self, tmp_data_dir, sample_workspace):
        from auth_manager import create_invite, get_workspace_invites
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_invite(ws_id, "a@test.com", "agent", "admin")
        create_invite(ws_id, "b@test.com", "viewer", "admin")
        invites = get_workspace_invites(ws_id)
        assert len(invites) == 2


class TestApiKeyAuth:
    def test_workspace_api_key_validates(self, tmp_data_dir, sample_workspace):
        from auth_manager import validate_api_key
        api_key = sample_workspace["workspace"]["api_key"]
        result = validate_api_key(api_key)
        assert result is not None
        assert result["workspace_id"] == sample_workspace["workspace"]["workspace_id"]

    def test_invalid_api_key_rejected(self, tmp_data_dir):
        from auth_manager import validate_api_key
        result = validate_api_key("invalid_key_xyz")
        assert result is None

    def test_legacy_api_key_works(self, tmp_data_dir):
        from auth_manager import validate_api_key
        import os
        os.environ["NAZAR_API_KEY"] = "nazar_dev_key"
        result = validate_api_key("nazar_dev_key")
        assert result is not None


class TestBootstrap:
    def test_bootstrap_creates_workspace(self, tmp_data_dir):
        from auth_manager import bootstrap_default_workspace
        boot = bootstrap_default_workspace()
        assert boot["workspace"] is not None
        assert boot["user"] is not None
        assert boot["already_existed"] is False

    def test_bootstrap_idempotent(self, tmp_data_dir):
        from auth_manager import bootstrap_default_workspace
        bootstrap_default_workspace()
        boot2 = bootstrap_default_workspace()
        assert boot2["already_existed"] is True
