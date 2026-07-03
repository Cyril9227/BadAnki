# render_auth.py
# Signs and verifies the short-lived tokens that grant access to the
# unauthenticated /render/card/{id} page used by the screenshot function.

import hashlib
import hmac
import os
import time

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
