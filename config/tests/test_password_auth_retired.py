"""Password authentication is retired: every password path is closed, every
passwordless path still works, and the stored hashes are untouched."""

import json
import re

import pytest
from allauth.account.adapter import get_adapter
from allauth.account.models import EmailAddress
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
    authenticate,
    get_user,
    get_user_model,
)
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.urls import reverse

from config.middlewares import PASSWORD_AUTH_RETIRED_CODE
from sites.models import SiteAttributes
from sites.utils import _site_attributes_cache

pytestmark = pytest.mark.django_db

CODE_RE = r"^\s*([A-Z0-9]{6})\s*$"  # the sign-in code sits on its own line
PASSWORD = "Quasar-Field-Test-733!"  # noqa: S105


@pytest.fixture(autouse=True)
def _test_site(settings):
    settings.STRIPE_SECRET_KEY = ""
    # allauth's login/signup rate limits live in the cache; an in-memory one
    # keeps the tests independent of a local Redis and of each other.
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    Site.objects.clear_cache()
    _site_attributes_cache.clear()
    cache.clear()
    site, _ = Site.objects.update_or_create(
        domain="testserver", defaults={"name": "Openbase Test"}
    )
    SiteAttributes.objects.update_or_create(
        site=site, defaults={"from_email": "team@openbase.cloud"}
    )
    settings.SITE_ID = site.id
    yield site
    Site.objects.clear_cache()
    _site_attributes_cache.clear()
    cache.clear()


def _create_user(email, password=PASSWORD, *, verified=True, **fields):
    user = get_user_model().objects.create_user(email, password, **fields)
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=verified)
    return user


def _post(client, path, payload, **headers):
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HOST="testserver",
        **headers,
    )


def test_settings_are_passwordless(settings):
    assert settings.PASSWORD_AUTH_ENABLED is False
    assert settings.ACCOUNT_SIGNUP_FIELDS == ["email*"]
    assert "config.middlewares.PasswordAuthRetiredMiddleware" in settings.MIDDLEWARE
    # Existing sessions and refresh tokens name these backends; see settings.py.
    assert settings.AUTHENTICATION_BACKENDS == (
        "django.contrib.auth.backends.ModelBackend",
        "allauth.account.auth_backends.AuthenticationBackend",
    )


def test_adapter_refuses_a_correct_password_and_keeps_the_hash(rf):
    user = _create_user("keeps-hash@resend.dev")
    request = rf.post("/_allauth/browser/v1/auth/login")

    assert (
        get_adapter().authenticate(request, email=user.email, password=PASSWORD) is None
    )
    user.refresh_from_db()
    assert user.has_usable_password()
    assert user.check_password(PASSWORD)
    # The backends themselves still work, for sessions (below) and for the
    # PASSWORD_AUTH_ENABLED rollback.
    assert authenticate(request=None, email=user.email, password=PASSWORD) == user


@pytest.mark.parametrize(
    "backend_path",
    [
        "django.contrib.auth.backends.ModelBackend",
        "allauth.account.auth_backends.AuthenticationBackend",
    ],
)
def test_sessions_signed_in_before_the_change_stay_signed_in(rf, backend_path):
    user = _create_user("still-signed-in@resend.dev")
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = backend_path
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.save()
    request = rf.get("/")
    request.session = store

    assert get_user(request) == user


@pytest.mark.parametrize("client_kind", ["browser", "app"])
def test_headless_password_login_is_refused_with_the_retired_code(client, client_kind):
    user = _create_user(f"login-{client_kind}@resend.dev")

    response = _post(
        client,
        f"/_allauth/{client_kind}/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["status"] == 400
    assert payload["errors"] == [
        {
            "message": pytest.approx(payload["errors"][0]["message"]),
            "code": PASSWORD_AUTH_RETIRED_CODE,
            "param": "password",
        }
    ]
    assert "retired" in payload["errors"][0]["message"]


@pytest.mark.parametrize(
    "path",
    [
        "/_allauth/browser/v1/auth/password/request",
        "/_allauth/app/v1/auth/password/reset",
        "/_allauth/browser/v1/account/password/change",
    ],
)
def test_headless_password_management_is_refused_and_sends_no_mail(
    client, mailoutbox, path
):
    user = _create_user("reset@resend.dev")

    response = _post(client, path, {"email": user.email})

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == PASSWORD_AUTH_RETIRED_CODE
    assert "param" not in response.json()["errors"][0]
    assert mailoutbox == []


def test_classic_password_reset_page_is_refused(client, mailoutbox):
    assert client.get("/accounts/password/reset/").status_code == 403
    assert (
        client.post("/accounts/password/reset/", {"email": "x@resend.dev"}).status_code
        == 403
    )
    assert mailoutbox == []


def test_classic_login_page_renders_without_a_password_field(client):
    response = client.get("/accounts/login/", HTTP_HOST="testserver")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'name="password"' not in body
    assert "Forgot Password?" not in body
    assert "sign-in code" in body


def _confirm_login_code(client, mailoutbox, user, remote_addr):
    requested = _post(
        client,
        "/_allauth/app/v1/auth/code/request",
        {"email": user.email},
        REMOTE_ADDR=remote_addr,
    )
    assert requested.status_code == 401, requested.content
    session_token = requested.json()["meta"]["session_token"]
    assert any(
        flow["id"] == "login_by_code" and flow.get("is_pending")
        for flow in requested.json()["data"]["flows"]
    ), requested.json()
    assert len(mailoutbox) == 1
    codes = re.findall(CODE_RE, mailoutbox[0].body, flags=re.MULTILINE)
    assert codes, mailoutbox[0].body
    return _post(
        client,
        "/_allauth/app/v1/auth/code/confirm",
        {"code": codes[0]},
        HTTP_X_SESSION_TOKEN=session_token,
    )


def test_login_by_code_still_signs_in(client, mailoutbox):
    user = _create_user("code-login@resend.dev")

    confirmed = _confirm_login_code(client, mailoutbox, user, "10.9.9.21")

    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["meta"]["is_authenticated"] is True
    assert confirmed.json()["data"]["user"]["id"] == user.id


def test_login_by_code_verifies_a_never_verified_password_account(client, mailoutbox):
    """A password account that never finished email verification is not locked
    out: confirming the sign-in code verifies the address as a side effect."""
    user = _create_user("unverified-login@resend.dev", verified=False)

    confirmed = _confirm_login_code(client, mailoutbox, user, "10.9.9.23")

    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["meta"]["is_authenticated"] is True
    assert EmailAddress.objects.get(user=user).verified is True


@pytest.mark.parametrize("extra", [{}, {"password": PASSWORD}])
def test_signup_creates_a_passwordless_account(client, mailoutbox, extra):
    """New signups never get a password, including from installed clients that
    still send one."""
    email = f"signup-{len(extra)}@resend.dev"

    response = _post(
        client,
        "/_allauth/app/v1/auth/signup",
        {"email": email, **extra},
        REMOTE_ADDR="10.9.9.22",
    )

    assert response.status_code == 401, response.content
    assert any(
        flow["id"] == "verify_email" for flow in response.json()["data"]["flows"]
    )
    user = get_user_model().objects.get(email=email)
    assert user.has_usable_password() is False
    assert len(mailoutbox) == 1


def test_admin_login_sends_anonymous_users_to_the_product_login(client, settings):
    login_url = reverse("admin:login")

    response = client.get(f"{login_url}?next=/admin/users/user/")

    assert response.status_code == 302
    assert response["Location"] == f"{settings.LOGIN_URL}?next=/admin/users/user/"


def test_admin_login_form_post_never_signs_in(client, settings):
    staff = _create_user("admin-post@resend.dev", is_staff=True, is_superuser=True)

    response = client.post(
        reverse("admin:login"),
        {"username": staff.email, "password": PASSWORD, "next": "/admin/"},
    )

    assert response.status_code == 302
    assert response["Location"].startswith(settings.LOGIN_URL)
    assert client.session.get(SESSION_KEY) is None


def test_admin_login_lets_signed_in_staff_through(client):
    staff = _create_user("staff@resend.dev", is_staff=True)
    client.force_login(staff)

    response = client.get(reverse("admin:login"))

    assert response.status_code == 302
    assert response["Location"] == reverse("admin:index")


def test_admin_login_refuses_signed_in_non_staff(client):
    client.force_login(_create_user("member@resend.dev"))

    response = client.get(reverse("admin:login"))

    assert response.status_code == 403
