"""Tests for acknowledgment-based refresh token rotation.

A refresh token must stay usable until the token issued from it is first
used, so refresh responses lost in transit (mobile suspend, laptop sleep)
or concurrent refreshes from multiple local processes do not strand
clients with a dead token.
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
        email="rotation@example.com",
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


def test_refresh_rotates_and_returns_new_token(user, session, initial_refresh_token):
    strategy = OpenbaseJWTTokenStrategy()
    result = strategy.refresh_token(initial_refresh_token)
    assert result is not None
    access_token, next_refresh_token = result
    assert access_token
    assert next_refresh_token != initial_refresh_token


def test_old_token_survives_until_new_token_is_used(
    user, session, initial_refresh_token
):
    strategy = OpenbaseJWTTokenStrategy()

    # First refresh; pretend the response was lost in transit.
    assert strategy.refresh_token(initial_refresh_token) is not None

    # The client retries with the old token and succeeds.
    retry = strategy.refresh_token(initial_refresh_token)
    assert retry is not None
    _, received_token = retry

    # Using the received token acknowledges it, retiring the old token.
    assert strategy.refresh_token(received_token) is not None
    assert strategy.refresh_token(initial_refresh_token) is None


def test_using_a_token_retires_lost_siblings(user, session, initial_refresh_token):
    strategy = OpenbaseJWTTokenStrategy()

    lost = strategy.refresh_token(initial_refresh_token)
    received = strategy.refresh_token(initial_refresh_token)
    assert lost is not None
    assert received is not None
    _, lost_token = lost
    _, received_token = received

    assert strategy.refresh_token(received_token) is not None

    # Both the parent and the never-received sibling are now dead.
    assert strategy.refresh_token(initial_refresh_token) is None
    assert strategy.refresh_token(lost_token) is None


def test_invalid_token_is_rejected(db):
    strategy = OpenbaseJWTTokenStrategy()
    assert strategy.refresh_token("not-a-token") is None
