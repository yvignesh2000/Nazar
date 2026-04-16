"""
Nazar — Auth & Workspace Manager

Handles:
- User accounts (email + hashed password)
- Workspace (tenant) isolation
- Role-based access control (Owner > Admin > Agent > Viewer)
- Session tokens (signed JWT-like tokens, no external dependency)
- API key management per workspace
- Invitation flow

Roles:
  owner   — Full control. Can delete workspace, manage billing, manage users.
   admin   — Manage contacts, campaigns, templates, settings. Cannot delete workspace.
  agent   — Read + reply to conversations. Cannot configure settings.
  viewer  — Read-only. Can see pipeline and analytics but not send messages.

Storage layout:
  data/auth/
    workspaces.json       — workspace registry
    users.json            — user accounts (passwords hashed with bcrypt-like PBKDF2)
    sessions.json         — active session tokens
    invites.json          — pending invitations
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "auth"

# File-level lock to prevent concurrent read-modify-write race conditions
_auth_lock = threading.Lock()

ROLES = ["owner", "admin", "agent", "viewer"]
ROLE_PERMISSIONS = {
    "owner":  {"read", "write", "send", "configure", "manage_users", "billing"},
    "admin":  {"read", "write", "send", "configure", "manage_users"},
    "agent":  {"read", "send"},
    "viewer": {"read"},
}

SESSION_TTL_SECONDS = 86400 * 7   # 7 days
TOKEN_SECRET = None  # loaded lazily from env or generated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _token_secret() -> str:
    global TOKEN_SECRET
    if TOKEN_SECRET:
        return TOKEN_SECRET
    secret = os.environ.get("NAZAR_TOKEN_SECRET", "")
    if not secret:
        # Store in data/auth/ (inside Docker volume)
        secret_path = DATA_DIR / ".token_secret"
        legacy_path = DATA_DIR.parent / ".token_secret"
        _ensure_dir()
        if secret_path.exists():
            secret = secret_path.read_text().strip()
        elif legacy_path.exists():
            # Migrate from legacy location
            secret = legacy_path.read_text().strip()
            secret_path.write_text(secret)
            secret_path.chmod(0o600)
        else:
            secret = secrets.token_hex(32)
            secret_path.write_text(secret)
            secret_path.chmod(0o600)
    TOKEN_SECRET = secret
    return secret


@contextmanager
def _locked_file(filename: str):
    """
    Context manager that acquires the auth lock and yields (data, save_fn).
    Ensures no two threads can read-modify-write the same file concurrently.
    Usage:
        with _locked_file("users.json") as (data, save_fn):
            data["new_user"] = {...}
            save_fn(data)
    """
    with _auth_lock:
        data = _load_unlocked(filename)
        def save_fn(new_data):
            _save_unlocked(filename, new_data)
        yield data, save_fn


def _load_unlocked(filename: str) -> dict:
    """Load without lock — use inside _locked_file or when lock is already held."""
    _ensure_dir()
    path = DATA_DIR / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_unlocked(filename: str, data: dict):
    """Save without lock — use inside _locked_file or when lock is already held."""
    _ensure_dir()
    path = DATA_DIR / filename
    # Atomic write: write to temp file then rename
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _load(filename: str) -> dict:
    """Thread-safe read of a JSON auth file."""
    with _auth_lock:
        return _load_unlocked(filename)


def _save(filename: str, data: dict):
    """Thread-safe write of a JSON auth file."""
    with _auth_lock:
        _save_unlocked(filename, data)


def _load_list(filename: str) -> list:
    _ensure_dir()
    path = DATA_DIR / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_list(filename: str, data: list):
    _ensure_dir()
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2 with SHA-256 — no bcrypt dependency needed)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2$sha256$200000${salt}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        parts = stored_hash.split("$")
        if parts[0] != "pbkdf2" or parts[1] != "sha256":
            return False
        iterations = int(parts[2])
        salt = parts[3]
        expected = parts[4]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session tokens (HMAC-signed, stateless-ish but also tracked server-side)
# ---------------------------------------------------------------------------

def _make_token(user_id: str, workspace_id: str) -> str:
    """Generate a signed session token."""
    ts = str(int(time.time()))
    rand = secrets.token_hex(8)
    payload = f"{user_id}:{workspace_id}:{ts}:{rand}"
    sig = hmac.new(
        _token_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{payload}:{sig}"


def _verify_token_format(token: str) -> Optional[dict]:
    """Verify token signature and return payload dict or None."""
    try:
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected_sig = hmac.new(
            _token_secret().encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        inner = payload.split(":")
        if len(inner) != 4:
            return None
        user_id, workspace_id, ts, _ = inner
        age = time.time() - int(ts)
        if age > SESSION_TTL_SECONDS:
            return None
        return {"user_id": user_id, "workspace_id": workspace_id}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------

def create_workspace(
    name: str,
    owner_email: str,
    plan: str = "starter",
) -> dict:
    """
    Create a new workspace and an owner account.

    Returns the workspace dict.
    """
    workspace_id = "ws_" + uuid.uuid4().hex[:10]
    api_key = "nzr_" + secrets.token_urlsafe(32)
    now = datetime.now(IST).isoformat()

    workspace = {
        "workspace_id": workspace_id,
        "name": name,
        "owner_email": owner_email,
        "plan": plan,
        "api_key": api_key,
        "created_at": now,
        "active": True,
        "settings": {
            "timezone": "Asia/Kolkata",
            "language": "en",
            "bot_enabled": True,
        },
    }

    with _locked_file("workspaces.json") as (workspaces, save_fn):
        workspaces[workspace_id] = workspace
        save_fn(workspaces)

    logger.info(f"Workspace created: {workspace_id} ({name})")
    return workspace


def get_workspace(workspace_id: str) -> Optional[dict]:
    """Get a workspace by ID."""
    workspaces = _load("workspaces.json")
    return workspaces.get(workspace_id)


def get_workspace_by_api_key(api_key: str) -> Optional[dict]:
    """Look up a workspace by its API key."""
    workspaces = _load("workspaces.json")
    for ws in workspaces.values():
        if ws.get("api_key") == api_key:
            return ws
    return None


def update_workspace(workspace_id: str, **fields) -> dict:
    """Update workspace fields."""
    workspaces = _load("workspaces.json")
    if workspace_id not in workspaces:
        raise ValueError(f"Workspace {workspace_id} not found")
    workspaces[workspace_id].update(fields)
    _save("workspaces.json", workspaces)
    return workspaces[workspace_id]


def list_workspaces() -> list:
    """List all workspaces."""
    return list(_load("workspaces.json").values())


def regenerate_api_key(workspace_id: str) -> str:
    """Generate a new API key for a workspace."""
    new_key = "nzr_" + secrets.token_urlsafe(32)
    update_workspace(workspace_id, api_key=new_key)
    logger.info(f"API key regenerated for workspace {workspace_id}")
    return new_key


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(
    email: str,
    password: str,
    workspace_id: str,
    role: str = "agent",
    name: str = "",
) -> dict:
    """
    Create a user account.

    Returns the user dict (without password hash).
    Raises ValueError if email already exists in workspace or role is invalid.
    """
    if role not in ROLES:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {ROLES}")

    user_id = "usr_" + uuid.uuid4().hex[:10]
    now = datetime.now(IST).isoformat()

    user = {
        "user_id": user_id,
        "email": email,
        "name": name or email.split("@")[0],
        "workspace_id": workspace_id,
        "role": role,
        "password_hash": _hash_password(password),
        "active": True,
        "created_at": now,
        "last_login": None,
    }

    with _locked_file("users.json") as (users, save_fn):
        # Check duplicate email in this workspace (inside lock)
        for u in users.values():
            if u["email"] == email and u["workspace_id"] == workspace_id:
                raise ValueError(f"User with email {email} already exists in this workspace")
        users[user_id] = user
        save_fn(users)

    logger.info(f"User created: {user_id} ({email}) in workspace {workspace_id}")

    # Return without password hash
    safe = {k: v for k, v in user.items() if k != "password_hash"}
    return safe


def get_user(user_id: str) -> Optional[dict]:
    """Get a user by ID (without password hash)."""
    users = _load("users.json")
    u = users.get(user_id)
    if u:
        return {k: v for k, v in u.items() if k != "password_hash"}
    return None


def get_user_by_email(email: str, workspace_id: str = "default") -> Optional[dict]:
    """Look up a user by email within a workspace. If workspace_id is 'default', searches all."""
    users = _load("users.json")
    for u in users.values():
        ws_match = workspace_id == "default" or u["workspace_id"] == workspace_id
        if u["email"] == email and ws_match:
            return {k: v for k, v in u.items() if k != "password_hash"}
    return None


def list_workspace_users(workspace_id: str) -> list:
    """List all users in a workspace."""
    users = _load("users.json")
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in users.values()
        if u.get("workspace_id") == workspace_id
    ]


def update_user(user_id: str, **fields) -> dict:
    """Update user fields. Cannot update password_hash directly."""
    fields.pop("password_hash", None)
    if "role" in fields and fields["role"] not in ROLES:
        raise ValueError(f"Invalid role '{fields['role']}'")

    users = _load("users.json")
    if user_id not in users:
        raise ValueError(f"User {user_id} not found")
    users[user_id].update(fields)
    _save("users.json", users)
    return {k: v for k, v in users[user_id].items() if k != "password_hash"}


def delete_user(user_id: str):
    """Deactivate a user (soft delete)."""
    users = _load("users.json")
    if user_id in users:
        users[user_id]["active"] = False
        _save("users.json", users)


def change_password(user_id: str, old_password: str, new_password: str) -> bool:
    """Change a user's password. Returns True on success."""
    with _locked_file("users.json") as (users, save_fn):
        u = users.get(user_id)
        if not u:
            return False
        if not _verify_password(old_password, u["password_hash"]):
            return False
        users[user_id]["password_hash"] = _hash_password(new_password)
        save_fn(users)
    return True


def reset_password(user_id: str, new_password: str):
    """Admin reset of a user's password (no old password required)."""
    with _locked_file("users.json") as (users, save_fn):
        if user_id not in users:
            raise ValueError(f"User {user_id} not found")
        users[user_id]["password_hash"] = _hash_password(new_password)
        save_fn(users)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login(email: str, password: str, workspace_id: str = "default") -> Optional[str]:
    """
    Authenticate a user and return a session token, or None on failure.

    If workspace_id is "default", searches all workspaces for matching email.
    Tokens are HMAC-signed and expire after SESSION_TTL_SECONDS.
    """
    with _locked_file("users.json") as (users, save_fn):
        for u in users.values():
            email_match = u["email"] == email and u.get("active", True)
            ws_match = (
                workspace_id == "default"  # search all workspaces
                or u["workspace_id"] == workspace_id
            )
            if email_match and ws_match:
                if _verify_password(password, u["password_hash"]):
                    # Update last_login atomically
                    u["last_login"] = datetime.now(IST).isoformat()
                    save_fn(users)
                    actual_ws = u["workspace_id"]
                    token = _make_token(u["user_id"], actual_ws)
                    logger.info(f"Login: {email} in workspace {actual_ws}")
                    return token
    logger.warning(f"Failed login: {email} in workspace {workspace_id}")
    return None


def validate_token(token: str) -> Optional[dict]:
    """
    Validate a session token.

    Returns {user_id, workspace_id, user, workspace} or None.
    """
    payload = _verify_token_format(token)
    if not payload:
        return None

    # Check revocation list
    if is_token_revoked(token):
        return None

    user = get_user(payload["user_id"])
    if not user or not user.get("active", True):
        return None

    workspace = get_workspace(payload["workspace_id"])
    if not workspace or not workspace.get("active", True):
        return None

    if user["workspace_id"] != payload["workspace_id"]:
        return None

    return {
        "user_id": user["user_id"],
        "workspace_id": workspace["workspace_id"],
        "user": user,
        "workspace": workspace,
    }


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

_revoked_tokens = set()  # type: set
# Store in data/auth/ (inside Docker volume) — not in app root
_REVOKED_PATH = DATA_DIR / ".revoked_tokens.json"
# Legacy path for backward compat
_LEGACY_REVOKED_PATH = DATA_DIR.parent / ".revoked_tokens.json"


def _load_revoked():
    """Load persisted revocation list into memory on startup."""
    global _revoked_tokens
    _ensure_dir()
    # Check new location first, then legacy
    path = _REVOKED_PATH if _REVOKED_PATH.exists() else _LEGACY_REVOKED_PATH
    if path.exists():
        try:
            tokens = json.loads(path.read_text())
            # Filter out tokens that have also naturally expired
            valid_revoked = set()
            for t in tokens:
                if _verify_token_format(t) is not None:
                    valid_revoked.add(t)
            _revoked_tokens = valid_revoked
            # Migrate to new location if needed
            if path == _LEGACY_REVOKED_PATH:
                _persist_revoked()
        except Exception:
            _revoked_tokens = set()


def _persist_revoked():
    """Persist the revocation set to disk. Prunes expired tokens from disk only."""
    try:
        # Write all currently-revoked tokens to disk (don't prune from memory)
        _REVOKED_PATH.write_text(json.dumps(list(_revoked_tokens)), encoding="utf-8")
        _REVOKED_PATH.chmod(0o600)
    except Exception as e:
        logger.warning("Failed to persist revoked tokens: %s", e)


def revoke_token(token: str):
    """Add a token to the revocation list. Subsequent validate_token() calls will fail."""
    _revoked_tokens.add(token)
    _persist_revoked()
    logger.info("Session token revoked")


def is_token_revoked(token: str) -> bool:
    """Return True if the token has been explicitly revoked."""
    return token in _revoked_tokens


# Load revoked list on module import
_load_revoked()


def check_permission(token: str, permission: str) -> Optional[dict]:
    """
    Validate token and check if user has a specific permission.

    Returns auth context dict or None if invalid/unauthorized.
    """
    ctx = validate_token(token)
    if not ctx:
        return None
    role = ctx["user"].get("role", "viewer")
    if permission not in ROLE_PERMISSIONS.get(role, set()):
        return None
    return ctx


# ---------------------------------------------------------------------------
# API key auth (for machine-to-machine access)
# ---------------------------------------------------------------------------

def validate_api_key(api_key: str) -> Optional[dict]:
    """
    Validate a workspace API key.

    Returns workspace dict or None.
    Used for dashboard-to-backend calls with the legacy X-Nazar-Key header.
    Also supports the new per-workspace keys (nzr_... prefix).
    """
    # Legacy single key
    legacy_key = os.environ.get("NAZAR_API_KEY", "nazar_dev_key")
    if api_key == legacy_key:
        # Return a stub workspace for backward compatibility
        return {
            "workspace_id": "default",
            "name": "Default Workspace",
            "plan": "starter",
            "api_key": api_key,
        }

    # Per-workspace key
    return get_workspace_by_api_key(api_key)


# ---------------------------------------------------------------------------
# Invitation system
# ---------------------------------------------------------------------------

def create_invite(
    workspace_id: str,
    email: str,
    role: str,
    invited_by: str,
) -> dict:
    """
    Create an invitation for a new user to join a workspace.

    Returns the invite dict with a token.
    """
    if role not in ROLES or role == "owner":
        raise ValueError(f"Invalid invite role '{role}'")

    invites = _load("invites.json")
    invite_token = secrets.token_urlsafe(24)
    now = datetime.now(IST)
    expires = (now + timedelta(days=7)).isoformat()

    invite = {
        "token": invite_token,
        "workspace_id": workspace_id,
        "email": email,
        "role": role,
        "invited_by": invited_by,
        "created_at": now.isoformat(),
        "expires_at": expires,
        "accepted": False,
    }
    invites[invite_token] = invite
    _save("invites.json", invites)
    logger.info(f"Invite created: {email} → workspace {workspace_id} as {role}")
    return invite


def accept_invite(token: str, name: str, password: str) -> Optional[dict]:
    """
    Accept an invitation and create the user account.

    Returns the created user dict or None if invite is invalid/expired.
    """
    invites = _load("invites.json")
    invite = invites.get(token)
    if not invite or invite.get("accepted"):
        return None

    # Check expiry
    try:
        expires = datetime.fromisoformat(invite["expires_at"])
        if datetime.now(IST) > expires:
            return None
    except Exception:
        return None

    # Create user
    user = create_user(
        email=invite["email"],
        password=password,
        workspace_id=invite["workspace_id"],
        role=invite["role"],
        name=name,
    )

    # Mark accepted
    invites[token]["accepted"] = True
    invites[token]["accepted_at"] = datetime.now(IST).isoformat()
    _save("invites.json", invites)

    return user


def get_workspace_invites(workspace_id: str) -> list:
    """List pending invitations for a workspace."""
    invites = _load("invites.json")
    return [
        i for i in invites.values()
        if i["workspace_id"] == workspace_id and not i.get("accepted")
    ]


# ---------------------------------------------------------------------------
# Bootstrap helper
# ---------------------------------------------------------------------------

def bootstrap_default_workspace() -> dict:
    """
    Create the default workspace and owner account if none exists.

    Called at startup for single-tenant / dev mode.
    Returns {workspace, user, already_existed, password_change_required}.
    """
    workspaces = _load("workspaces.json")
    if workspaces:
        # Already set up
        ws = next(iter(workspaces.values()))
        users = list_workspace_users(ws["workspace_id"])
        return {
            "workspace": ws,
            "user": users[0] if users else None,
            "already_existed": True,
            "password_change_required": False,
        }

    # Create default — use env var for password if set, otherwise generate random
    default_password = os.environ.get("NAZAR_ADMIN_PASSWORD", "")
    password_change_required = False
    if not default_password:
        default_password = "changeme123"
        password_change_required = True

    ws = create_workspace(
        name="My Business",
        owner_email="admin@nazar.app",
        plan="starter",
    )
    user = create_user(
        email="admin@nazar.app",
        password=default_password,
        workspace_id=ws["workspace_id"],
        role="owner",
        name="Admin",
    )
    # Mark user as needing password change
    if password_change_required:
        with _locked_file("users.json") as (users_data, save_fn):
            if user["user_id"] in users_data:
                users_data[user["user_id"]]["password_change_required"] = True
                save_fn(users_data)

    if password_change_required:
        logger.warning(
            "⚠️  Default workspace bootstrapped with default password. "
            "Change it immediately at login!"
        )
    else:
        logger.info(f"Default workspace bootstrapped: {ws['workspace_id']}")

    return {
        "workspace": ws,
        "user": user,
        "already_existed": False,
        "password_change_required": password_change_required,
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    # Clean
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    # 1. Create workspace
    ws = create_workspace("Acme Sales", "owner@acme.com", plan="growth")
    assert ws["workspace_id"].startswith("ws_")
    assert ws["api_key"].startswith("nzr_")
    print(f"✅ Workspace created: {ws['workspace_id']}")

    # 2. Create users
    owner = create_user("owner@acme.com", "Secret123!", ws["workspace_id"], role="owner", name="Owner")
    agent = create_user("agent@acme.com", "Pass456!", ws["workspace_id"], role="agent", name="Agent")
    assert "password_hash" not in owner
    print(f"✅ Users created: {owner['user_id']}, {agent['user_id']}")

    # 3. Login
    token = login("owner@acme.com", "Secret123!", ws["workspace_id"])
    assert token is not None
    print(f"✅ Login successful, token: {token[:20]}...")

    wrong_token = login("owner@acme.com", "wrongpassword", ws["workspace_id"])
    assert wrong_token is None
    print("✅ Bad password rejected")

    # 4. Validate token
    ctx = validate_token(token)
    assert ctx is not None
    assert ctx["user"]["email"] == "owner@acme.com"
    print(f"✅ Token valid: {ctx['user']['role']}")

    # 5. Permission check
    assert check_permission(token, "billing") is not None
    agent_token = login("agent@acme.com", "Pass456!", ws["workspace_id"])
    assert check_permission(agent_token, "billing") is None  # agents can't bill
    assert check_permission(agent_token, "send") is not None  # agents can send
    print("✅ Permission checks passed")

    # 6. API key auth
    result = validate_api_key(ws["api_key"])
    assert result is not None
    assert result["workspace_id"] == ws["workspace_id"]
    print("✅ API key auth works")

    # 7. Invite system
    invite = create_invite(ws["workspace_id"], "new@acme.com", "admin", owner["user_id"])
    assert invite["token"]
    new_user = accept_invite(invite["token"], "New Admin", "newpass123")
    assert new_user is not None
    assert new_user["email"] == "new@acme.com"
    print(f"✅ Invite accepted: {new_user['user_id']}")

    # 8. Change password
    result = change_password(owner["user_id"], "Secret123!", "NewSecret456!")
    assert result is True
    token2 = login("owner@acme.com", "NewSecret456!", ws["workspace_id"])
    assert token2 is not None
    print("✅ Password change works")

    # 9. List workspace users
    users = list_workspace_users(ws["workspace_id"])
    assert len(users) >= 3
    print(f"✅ Workspace users: {len(users)}")

    # 10. Bootstrap
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    boot = bootstrap_default_workspace()
    assert not boot["already_existed"]
    boot2 = bootstrap_default_workspace()
    assert boot2["already_existed"]
    print("✅ Bootstrap works")

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\n✅ All auth_manager tests passed!")
