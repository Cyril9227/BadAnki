# render_auth.py
# Signs and verifies the app's short-lived HMAC tokens: access to the
# unauthenticated /render/card/{id} page used by the screenshot function,
# and the Telegram deep-link tokens that prove account ownership.

import hashlib
import hmac
import os
import time
import uuid

_CONTEXT = "render-card"


def _secret() -> bytes:
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return secret.encode()


def sign_render_request(card_id: int, expires_at: int) -> str:
    """Returns the hex HMAC for a render request. The same construction is
    implemented in api/render-card.js — keep them in sync."""
    payload = f"{_CONTEXT}:{card_id}:{expires_at}".encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def verify_render_request(card_id: int, expires_at: int, signature: str) -> bool:
    if expires_at < time.time():
        return False
    return hmac.compare_digest(sign_render_request(card_id, expires_at), signature)


# --- Telegram account linking ---
# Telegram caps /start deep-link payloads at 64 chars of [A-Za-z0-9_-],
# hence the dashless uuid and truncated signature: 32 + 10 + 16 hex chars
# plus two separators.

_LINK_CONTEXT = "telegram-link"
TELEGRAM_LINK_TTL_SECONDS = 900


def _sign_telegram_link(uid: uuid.UUID, expires_at: int) -> str:
    payload = f"{_LINK_CONTEXT}:{uid}:{expires_at}".encode()
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()[:16]


def make_telegram_link_token(auth_user_id) -> str:
    uid = uuid.UUID(str(auth_user_id))
    expires_at = int(time.time()) + TELEGRAM_LINK_TTL_SECONDS
    return f"{uid.hex}_{expires_at}_{_sign_telegram_link(uid, expires_at)}"


def verify_telegram_link_token(token: str) -> str | None:
    """Returns the auth_user_id the token was issued for, or None."""
    try:
        uid_hex, exp_text, signature = token.split("_")
        uid = uuid.UUID(hex=uid_hex)
        expires_at = int(exp_text)
    except ValueError:
        return None
    if expires_at < time.time():
        return None
    if not hmac.compare_digest(_sign_telegram_link(uid, expires_at), signature):
        return None
    return str(uid)
