import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    DEVICE_KEY_PREFIX,
    InvalidTokenError,
    create_token,
    decode_token,
    generate_device_key,
    hash_api_key,
    hash_password,
    password_needs_rehash,
    verify_password,
)

SETTINGS = Settings(jwt_secret_key="unit-test-secret-that-is-long-enough-1234")


def test_password_hash_round_trip() -> None:
    hashed = hash_password("s3cret-pass")

    assert hashed.startswith("$argon2id$")
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)
    assert not password_needs_rehash(hashed)


def test_unknown_user_never_verifies() -> None:
    assert not verify_password("not-a-real-password", None)


def test_corrupt_hash_does_not_crash() -> None:
    assert not verify_password("anything", "not-an-argon2-hash")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token, claims = create_token(SETTINGS, user_id, "access")

    decoded = decode_token(SETTINGS, token, expected_type="access")

    assert decoded.subject == user_id
    assert decoded.jti == claims.jti
    assert decoded.token_type == "access"


def test_refresh_token_cannot_be_used_as_access_token() -> None:
    token, _ = create_token(SETTINGS, uuid.uuid4(), "refresh")

    with pytest.raises(InvalidTokenError, match="expected a access token"):
        decode_token(SETTINGS, token, expected_type="access")


def test_expired_token_is_rejected() -> None:
    long_ago = datetime.now(UTC) - timedelta(days=1)
    token, _ = create_token(SETTINGS, uuid.uuid4(), "access", now=long_ago)

    with pytest.raises(InvalidTokenError):
        decode_token(SETTINGS, token, expected_type="access")


def test_token_signed_with_another_secret_is_rejected() -> None:
    other = Settings(jwt_secret_key="a-different-secret-for-the-attacker-12345")
    token, _ = create_token(other, uuid.uuid4(), "access")

    with pytest.raises(InvalidTokenError):
        decode_token(SETTINGS, token, expected_type="access")


def test_unsigned_none_algorithm_token_is_rejected() -> None:
    payload = {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4()), "exp": 9e9}
    token = jwt.encode(payload, key=None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        decode_token(SETTINGS, token, expected_type="access")


def test_token_with_missing_claims_is_rejected() -> None:
    token = jwt.encode({"sub": "x"}, SETTINGS.jwt_secret_key, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_token(SETTINGS, token, expected_type="access")


def test_device_keys_are_random_and_hashed() -> None:
    first, second = generate_device_key(), generate_device_key()

    assert first.plaintext != second.plaintext
    assert first.plaintext.startswith(DEVICE_KEY_PREFIX)
    assert first.hash == hash_api_key(first.plaintext)
    assert first.plaintext.startswith(first.prefix)
    assert first.plaintext not in first.hash
