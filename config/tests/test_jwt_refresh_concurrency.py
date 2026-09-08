"""Regression tests for concurrent refresh-token rotation.

Django's DB-backed sessions are whole-blob last-write-wins. Before
``refresh_token`` locked the session row and re-read its state, two truly
concurrent refreshes for the same session each read the same state, each
issued a child token, and both saved: the loser's save erased the winner's
freshly issued child jti, so the client holding it got a 401 on next use
and was logged out (production incident: two refreshes 1.9ms apart).

These tests simulate that interleave deterministically by injecting a
competing, fully committed rotation between the strategy's token
validation and its locked re-read of the session row (access-token
creation sits between the two, so it doubles as the injection point).
"""

import pytest
from allauth.headless.tokens.strategies.jwt import internal
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.contrib.sessions.backends.db import SessionStore

from config.jwt import OpenbaseJWTTokenStrategy


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="concurrency@example.com",
        password="irrelevant-1234",  # noqa: S106
    )


@pytest.fixture
def session(user):
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.save()
    return store


@pytest.fixture
def initial_refresh_token(user, session):
    token = internal.create_refresh_token(user, session)
    session.save()
    return token


def _inject_between_validation_and_lock(monkeypatch, competing):
    """Run ``competing`` once, after refresh-token validation but before
    the strategy's locked re-read of the session row."""
    original = internal.create_access_token
    ran = False

    def create_access_token_with_race(user, session, claims):
        nonlocal ran
        if not ran:
            ran = True
            competing()
        return original(user, session, claims)

    monkeypatch.setattr(internal, "create_access_token", create_access_token_with_race)


def test_concurrent_refresh_preserves_both_issued_tokens(
    monkeypatch, user, session, initial_refresh_token
):
    strategy = OpenbaseJWTTokenStrategy()
    competitor_result = []

    def competing_refresh():
        competitor_result.append(
            OpenbaseJWTTokenStrategy().refresh_token(initial_refresh_token)
        )

    _inject_between_validation_and_lock(monkeypatch, competing_refresh)

    result = strategy.refresh_token(initial_refresh_token)

    assert result is not None
    assert competitor_result
    assert competitor_result[0] is not None
    _, our_child = result
    _, competitor_child = competitor_result[0]
    assert our_child != competitor_child

    # Neither issued-and-returned refresh token was erased by the other's
    # session save: both children must still validate.
    assert internal.validate_refresh_token(our_child) is not None
    assert internal.validate_refresh_token(competitor_child) is not None


def test_token_retired_by_concurrent_request_is_rejected(
    monkeypatch, user, session, initial_refresh_token
):
    strategy = OpenbaseJWTTokenStrategy()
    received = strategy.refresh_token(initial_refresh_token)
    assert received is not None
    _, received_token = received

    def competing_ack():
        # Using the received child acknowledges it, retiring the parent
        # token while our request sits between validation and the lock.
        assert OpenbaseJWTTokenStrategy().refresh_token(received_token) is not None

    _inject_between_validation_and_lock(monkeypatch, competing_ack)

    # Serialized execution would reject the now-retired parent token; the
    # locked re-read must reach the same outcome instead of resurrecting it.
    assert strategy.refresh_token(initial_refresh_token) is None
