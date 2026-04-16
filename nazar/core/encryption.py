"""
Nazar — Per-Contact Encryption Layer

Every contact's data is encrypted with a unique key derived from:
  HKDF(master_secret + phone_number + salt)

This means:
- Each contact's data is independently encrypted
- Compromising one contact doesn't compromise others
- Without the master secret, disk data is useless
"""

import os
import json
import base64
from pathlib import Path
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet

# Master secret — in production, this comes from env var or vault
# IMPORTANT: Store in data/ directory so Docker volume mount persists it.
# Old location (.master_secret in app root) is checked for backward compat.
_DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_SECRET_PATH = _DATA_DIR / ".master_secret"
SALT_PATH = _DATA_DIR / ".salt"
_LEGACY_SECRET_PATH = Path(__file__).parent.parent / ".master_secret"
_LEGACY_SALT_PATH = Path(__file__).parent.parent / ".salt"


def _get_master_secret() -> bytes:
    """
    Load or generate the master secret.

    Priority:
    1. NAZAR_MASTER_SECRET env var (base64-encoded, for production/K8s)
    2. data/.master_secret file (persisted in Docker volume)
    3. Legacy .master_secret in app root (migrate to data/ on first read)
    4. Auto-generate and save to data/.master_secret
    """
    # 1. Environment variable (highest priority — for prod/K8s/vault)
    env_secret = os.environ.get("NAZAR_MASTER_SECRET", "")
    if env_secret:
        import base64
        return base64.b64decode(env_secret)

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 2. New location (data/ — inside Docker volume)
    if MASTER_SECRET_PATH.exists():
        return MASTER_SECRET_PATH.read_bytes()

    # 3. Legacy location — migrate to new path
    if _LEGACY_SECRET_PATH.exists():
        secret = _LEGACY_SECRET_PATH.read_bytes()
        MASTER_SECRET_PATH.write_bytes(secret)
        MASTER_SECRET_PATH.chmod(0o600)
        return secret

    # 4. Auto-generate
    secret = os.urandom(32)
    MASTER_SECRET_PATH.write_bytes(secret)
    MASTER_SECRET_PATH.chmod(0o600)
    return secret


def _get_salt() -> bytes:
    """Load or generate the salt. Same priority as master secret."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    if SALT_PATH.exists():
        return SALT_PATH.read_bytes()

    # Legacy migration
    if _LEGACY_SALT_PATH.exists():
        salt = _LEGACY_SALT_PATH.read_bytes()
        SALT_PATH.write_bytes(salt)
        SALT_PATH.chmod(0o600)
        return salt

    salt = os.urandom(16)
    SALT_PATH.write_bytes(salt)
    SALT_PATH.chmod(0o600)
    return salt


def derive_user_key(phone: str) -> bytes:
    """Derive a unique Fernet key for a user based on their phone number."""
    master = _get_master_secret()
    salt = _get_salt()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=phone.encode("utf-8"),
    )
    raw_key = hkdf.derive(master)
    return base64.urlsafe_b64encode(raw_key)


def get_fernet(phone: str) -> Fernet:
    """Get a Fernet instance for a specific user."""
    return Fernet(derive_user_key(phone))


def encrypt_data(phone: str, data: str) -> bytes:
    """Encrypt a string for a specific user."""
    f = get_fernet(phone)
    return f.encrypt(data.encode("utf-8"))


def decrypt_data(phone: str, token: bytes) -> str:
    """Decrypt data for a specific user."""
    f = get_fernet(phone)
    return f.decrypt(token).decode("utf-8")


def encrypt_file(phone: str, filepath: Path, content: str):
    """Write encrypted content to a file."""
    encrypted = encrypt_data(phone, content)
    filepath.write_bytes(encrypted)


def decrypt_file(phone: str, filepath: Path) -> str:
    """Read and decrypt content from a file."""
    encrypted = filepath.read_bytes()
    return decrypt_data(phone, encrypted)


def encrypt_json(phone: str, filepath: Path, data: dict):
    """Write encrypted JSON to a file."""
    encrypt_file(phone, filepath, json.dumps(data, ensure_ascii=False, indent=2))


def decrypt_json(phone: str, filepath: Path) -> dict:
    """Read and decrypt JSON from a file."""
    return json.loads(decrypt_file(phone, filepath))


# --- Test ---
if __name__ == "__main__":
    test_phone = "+919876543210"
    test_data = "I had a fight with my mom today. She compared me to my cousin again."

    encrypted = encrypt_data(test_phone, test_data)
    decrypted = decrypt_data(test_phone, encrypted)

    assert decrypted == test_data
    print("✅ Encryption test passed")
    print(f"   Original:  {test_data[:50]}...")
    print(f"   Encrypted: {encrypted[:50]}...")
    print(f"   Decrypted: {decrypted[:50]}...")

    # Verify different phone = different key = can't decrypt
    try:
        decrypt_data("+919999999999", encrypted)
        print("❌ FAIL: Different phone decrypted the data!")
    except Exception:
        print("✅ Different phone number cannot decrypt — isolation works")
