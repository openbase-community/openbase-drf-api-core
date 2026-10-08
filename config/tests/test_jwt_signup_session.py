import json
import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.http import HttpRequest

from config.jwt import ApiCoreJWTTokenStrategy
from sites.models import SiteAttributes
from sites.utils import _site_attributes_cache


def test_unauthenticated_signup_can_expose_session_token(db):
    request = HttpRequest()
    request.user = AnonymousUser()
    request.session = SessionStore()
    request.session["account_signup_email"] = "field-test@resend.dev"

    token = ApiCoreJWTTokenStrategy().create_session_token(request)

    assert token == request.session.session_key
    assert isinstance(token, str)


@pytest.fixture(autouse=True)
def _fresh_site_attributes_cache():
    # The per-host memory cache remembers "no attributes" from any request an
    # earlier test made before creating SiteAttributes; the verification mail
    # then has no from address.
    # django.contrib.sites keeps its own per-host cache of Site rows, which
    # go stale across test databases and then miss their SiteAttributes.
    Site.objects.clear_cache()
    _site_attributes_cache.clear()
    # allauth's "confirm_email" rate limit lives in the process-wide cache;
    # with code-based verification a limited signup aborts the whole login
    # instead of just skipping the mail.
    cache.clear()
    yield
    Site.objects.clear_cache()
    _site_attributes_cache.clear()
    cache.clear()


@pytest.mark.django_db
def test_mandatory_verification_signup_returns_auth_flow_session(client, settings):
    settings.STRIPE_SECRET_KEY = ""
    site, _ = Site.objects.update_or_create(
        domain="testserver", defaults={"name": "Openbase Test"}
    )
    SiteAttributes.objects.update_or_create(
        site=site, defaults={"from_email": "team@openbase.cloud"}
    )
    settings.SITE_ID = site.id

    response = client.post(
        "/_allauth/app/v1/auth/signup",
        data=json.dumps(
            {
                "email": "delivered+openbase-field-jwt-session@resend.dev",
                "password": "Quasar-Field-Test-731!",
            }
        ),
        content_type="application/json",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["meta"]["session_token"]
    assert any(flow["id"] == "verify_email" for flow in payload["data"]["flows"])


@pytest.mark.django_db
def test_signup_verifies_with_an_emailed_code_and_signs_in(
    client, settings, mailoutbox
):
    """Phone-only signup: the code from the verification email, typed into the
    app, completes the session without a browser round trip."""
    settings.STRIPE_SECRET_KEY = ""
    settings.ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = True
    site, _ = Site.objects.update_or_create(
        domain="testserver", defaults={"name": "Openbase Test"}
    )
    SiteAttributes.objects.update_or_create(
        site=site, defaults={"from_email": "team@openbase.cloud"}
    )
    settings.SITE_ID = site.id

    signup = client.post(
        "/_allauth/app/v1/auth/signup",
        data=json.dumps(
            {
                "email": "delivered+openbase-field-code-signup@resend.dev",
                "password": "Quasar-Field-Test-732!",
            }
        ),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="10.9.9.9",  # own bucket for the per-IP signup throttle
    )
    assert signup.status_code == 401
    session_token = signup.json()["meta"]["session_token"]
    assert any(
        flow["id"] == "verify_email" for flow in signup.json()["data"]["flows"]
    ), signup.json()
    assert len(mailoutbox) == 1
    codes = re.findall(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", mailoutbox[0].body)
    assert codes, mailoutbox[0].body

    verified = client.post(
        "/_allauth/app/v1/auth/email/verify",
        data=json.dumps({"key": codes[0]}),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_X_SESSION_TOKEN=session_token,
    )
    assert verified.status_code == 200, verified.content
    assert verified.json()["meta"]["is_authenticated"] is True
