import json

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sites.models import Site
from django.http import HttpRequest

from config.jwt import ApiCoreJWTTokenStrategy
from sites.models import SiteAttributes


def test_unauthenticated_signup_can_expose_session_token(db):
    request = HttpRequest()
    request.user = AnonymousUser()
    request.session = SessionStore()
    request.session["account_signup_email"] = "field-test@resend.dev"

    token = ApiCoreJWTTokenStrategy().create_session_token(request)

    assert token == request.session.session_key
    assert isinstance(token, str)


@pytest.mark.django_db
def test_mandatory_verification_signup_returns_auth_flow_session(
    client, settings
):
    settings.STRIPE_SECRET_KEY = ""
    site, _ = Site.objects.update_or_create(
        domain="testserver", defaults={"name": "Openbase Test"}
    )
    SiteAttributes.objects.update_or_create(
        site=site, defaults={"from_email": "team@openbase.cloud"}
    )

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
