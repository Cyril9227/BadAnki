# Unit tests for the HMAC tokens guarding the card render page.

import time

import pytest

from render_auth import sign_render_request, verify_render_request


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
