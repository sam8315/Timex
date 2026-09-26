"""Security tests for application session signing."""

import pytest

from web.session import create_session_token, verify_session_token


def test_session_token_round_trip():
    token = create_session_token("user-1", "user")
    assert verify_session_token(token) == {"user_id": "user-1", "role": "user"}


def test_session_token_rejects_tampering():
    token = create_session_token("user-1", "user")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert verify_session_token(tampered) is None


def test_session_secret_is_not_a_code_default():
    from web.config import WebConfig

    assert WebConfig.SECRET_KEY
    assert WebConfig.SESSION_MIDDLEWARE_SECRET_KEY
    assert WebConfig.SECRET_KEY != "timex-change-this-secret-key-2026"
    assert WebConfig.SESSION_MIDDLEWARE_SECRET_KEY != "timex-web-secret-key-2024-change-in-production"
    assert len(WebConfig.SECRET_KEY) >= 32
    assert len(WebConfig.SESSION_MIDDLEWARE_SECRET_KEY) >= 32
