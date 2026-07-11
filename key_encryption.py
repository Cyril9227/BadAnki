# key_encryption.py
# Encryption at rest for user LLM API keys, keyed off the existing
# SECRET_KEY (Fernet: AES-128-CBC + HMAC). Ciphertext carries an "enc:"
# prefix so rows written before encryption shipped keep working: decrypt
# passes unprefixed values through unchanged, and the next save of the
# settings form re-writes them encrypted.

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from env_utils import clean_env_value

logger = logging.getLogger(__name__)

_PREFIX = "enc:"
_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        secret = clean_env_value("SECRET_KEY")
        if not secret:
            raise RuntimeError("SECRET_KEY is required to encrypt/decrypt stored API keys.")
        _fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
    return _fernet


def encrypt_secret(value):
    """Encrypts a secret for storage. None/empty pass through unchanged."""
    if not value:
        return value
    return _PREFIX + _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    """Reverses encrypt_secret. Values without the prefix (legacy plaintext
    rows) pass through unchanged. An undecryptable value — SECRET_KEY was
    rotated — reads as "no key" instead of breaking every request; the user
    re-enters the key in Settings."""
    if not value or not value.startswith(_PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.error("A stored API key failed to decrypt — was SECRET_KEY rotated?")
        return None
