import pytest
from allauth.headless.tokens.strategies.jwt import internal
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
)
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest

from config.jwt import ApiCoreJWTTokenStrategy


@pytest.fixture(autouse=True)
def _disable_stripe(settings):
    settings.STRIPE_SECRET_KEY = ""


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="analytics@example.com",
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


def test_create_access_token_payload_notifies_jwt_analytics_receivers(
    monkeypatch, user, session
):
    calls = []

    def receiver(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "config.jwt_analytics.get_jwt_analytics_receivers",
        lambda: (receiver,),
    )
    request = HttpRequest()
    request.user = user
    request.session = session

    payload = ApiCoreJWTTokenStrategy().create_access_token_payload(request)

    assert payload is not None
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert len(calls) == 1
    assert calls[0]["user"] == user
    assert calls[0]["session"] == session
    assert calls[0]["request"] == request
    assert calls[0]["source"] == "headless_token_payload"


def test_refresh_token_notifies_jwt_analytics_receivers(monkeypatch, user, session):
    calls = []

    def receiver(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "config.jwt_analytics.get_jwt_analytics_receivers",
        lambda: (receiver,),
    )
    refresh_token = internal.create_refresh_token(user, session)
    session.save()

    result = ApiCoreJWTTokenStrategy().refresh_token(refresh_token)

    assert result is not None
    assert len(calls) == 1
    assert calls[0]["user"] == user
    assert calls[0]["session"].session_key == session.session_key
    assert calls[0]["request"] is None
    assert calls[0]["source"] == "refresh_token"
