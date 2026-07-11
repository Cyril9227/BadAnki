# Unit tests for API-key encryption at rest (pure functions, no DB required).

import os

os.environ.setdefault("SECRET_KEY", "testsecret")

from key_encryption import decrypt_secret, encrypt_secret


def test_round_trip():
    ciphertext = encrypt_secret("sk-super-secret")
    assert ciphertext.startswith("enc:")
    assert "sk-super-secret" not in ciphertext
    assert decrypt_secret(ciphertext) == "sk-super-secret"


def test_each_encryption_is_unique_but_decrypts_the_same():
    a, b = encrypt_secret("same-key"), encrypt_secret("same-key")
    assert a != b  # Fernet includes a random IV
    assert decrypt_secret(a) == decrypt_secret(b) == "same-key"


def test_legacy_plaintext_passes_through():
    # Rows written before encryption shipped have no prefix — they must keep
    # working untouched until their next save re-encrypts them.
    assert decrypt_secret("AIzaSy-legacy-plaintext") == "AIzaSy-legacy-plaintext"


def test_none_and_empty_pass_through():
    assert encrypt_secret(None) is None
    assert encrypt_secret("") == ""
    assert decrypt_secret(None) is None
    assert decrypt_secret("") == ""


def test_undecryptable_value_reads_as_no_key():
    # e.g. SECRET_KEY rotated: better "Not set" in Settings than a 500 on
    # every request.
    assert decrypt_secret("enc:not-a-real-fernet-token") is None
