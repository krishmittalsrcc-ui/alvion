"""Passwords, sessions and at-rest encryption of provider API keys."""
import base64
import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from . import config

# scrypt needs OpenSSL 1.1+, which the macOS CommandLineTools Python does not
# expose. PBKDF2-HMAC-SHA256 is always available; iteration count per OWASP.
_PBKDF2_ROUNDS = 600_000


# --- passwords -------------------------------------------------------------

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                             _PBKDF2_ROUNDS, dklen=32)
    return base64.b64encode(dk).decode(), salt


def verify_password(password, stored_hash, salt):
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, stored_hash)


def new_token():
    return secrets.token_urlsafe(32)


# --- credential encryption -------------------------------------------------

def _master_key():
    """Load or create the local master key. 0600, never in the repo."""
    path = config.MASTER_KEY_PATH
    if not os.path.exists(path):
        key = Fernet.generate_key()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key
    with open(path, "rb") as f:
        return f.read().strip()


def encrypt(plaintext):
    return Fernet(_master_key()).encrypt(plaintext.encode())


def decrypt(token):
    try:
        return Fernet(_master_key()).decrypt(token).decode()
    except InvalidToken:
        raise ValueError(
            "Stored credential could not be decrypted. The master key in "
            "data/master.key has changed or been lost — re-enter the key in Settings."
        )


def mask(secret_value):
    """Show only enough to recognise a key. Never return a full secret to a client."""
    if not secret_value:
        return ""
    s = str(secret_value)
    return (s[:4] + "…" + s[-4:]) if len(s) > 12 else "…" * 4
