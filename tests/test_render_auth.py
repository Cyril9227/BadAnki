# Unit tests for the HMAC tokens guarding the card render page and
# Telegram account linking.

import time
import uuid

import pytest

from render_auth import (
    make_telegram_link_token,
    sign_render_request,
    verify_render_request,
    verify_telegram_link_token,
)


@pytest.fixture(autouse=True)
def secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")


def test_valid_signature_roundtrip():
    expires_at = int(time.time()) + 60
    sig = sign_render_request(42, expires_at)
    assert verify_render_request(42, expires_at, sig)


def test_expired_token_is_rejected():
    expires_at = int(time.time()) - 1
    sig = sign_render_request(42, expires_at)
    assert not verify_render_request(42, expires_at, sig)


def test_tampered_card_id_is_rejected():
    expires_at = int(time.time()) + 60
    sig = sign_render_request(42, expires_at)
    assert not verify_render_request(43, expires_at, sig)


def test_tampered_signature_is_rejected():
    expires_at = int(time.time()) + 60
    sig = sign_render_request(42, expires_at)
    assert not verify_render_request(42, expires_at, sig[:-1] + ("0" if sig[-1] != "0" else "1"))


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(RuntimeError):
        sign_render_request(42, int(time.time()) + 60)


def test_telegram_link_token_roundtrip():
    user_id = str(uuid.uuid4())
    token = make_telegram_link_token(user_id)
    # Telegram caps /start payloads at 64 chars of [A-Za-z0-9_-].
    assert len(token) <= 64
    assert verify_telegram_link_token(token) == user_id


def test_telegram_link_token_tampered_user_is_rejected():
    token = make_telegram_link_token(str(uuid.uuid4()))
    other = uuid.uuid4().hex
    _, exp, sig = token.split("_")
    assert verify_telegram_link_token(f"{other}_{exp}_{sig}") is None


def test_telegram_link_token_garbage_is_rejected():
    assert verify_telegram_link_token("not-a-token") is None
    assert verify_telegram_link_token("a_b_c") is None
