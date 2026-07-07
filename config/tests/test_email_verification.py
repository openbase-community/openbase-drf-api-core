import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import override_settings

from config.email_verification import user_has_verified_email
from config.middlewares import RequireVerifiedEmailMiddleware

pytestmark = pytest.mark.django_db


def test_user_has_verified_email_requires_verified_address():
    user = _create_user("unverified@example.com")
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )

    assert user_has_verified_email(user) is False


@override_settings(
    REQUIRE_VERIFIED_EMAIL_MESSAGE="Please verify your email address before continuing.",
    REQUIRE_VERIFIED_EMAIL_EXEMPT_PATH_PREFIXES=["/api/auth/"],
    REQUIRE_VERIFIED_EMAIL_AUTO_VERIFY_AUTHENTICATED=False,
)
def test_require_verified_email_blocks_unverified_api_request(rf):
    user = _create_user("blocked@example.com")
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )
    request = rf.get("/api/users/me/")
    request.user = user

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 403
    payload = json.loads(response.content)
    assert payload["code"] == "email_not_verified"
    assert payload["detail"] == "Please verify your email address before continuing."


@override_settings(REQUIRE_VERIFIED_EMAIL_EXEMPT_PATH_PREFIXES=["/api/auth/"])
def test_require_verified_email_allows_auth_api_request(rf):
    user = _create_user("auth@example.com")
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )
    request = rf.post("/api/auth/magic-link/request/")
    request.user = user

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 200


@override_settings(
    REQUIRE_VERIFIED_EMAIL_EXEMPT_PATH_PREFIXES=["/api/auth/"],
    REQUIRE_VERIFIED_EMAIL_AUTO_VERIFY_AUTHENTICATED=True,
)
def test_require_verified_email_can_auto_verify_authenticated_user(rf):
    user = _create_user("auto-verify@example.com")
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )
    request = rf.get("/api/users/me/")
    request.user = user

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 200
    assert user_has_verified_email(user) is True


def test_require_verified_email_allows_verified_api_request(rf):
    user = _create_user("verified@example.com")
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=True,
    )
    request = rf.get("/api/users/me/")
    request.user = user

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 200


@override_settings(
    REQUIRE_VERIFIED_EMAIL_EXEMPT_PATH_PREFIXES=["/api/auth/"],
    REQUIRE_VERIFIED_EMAIL_AUTO_VERIFY_AUTHENTICATED=False,
)
def test_require_verified_email_allows_staff_api_request(rf):
    user = _create_user("staff@example.com", is_staff=True)
    EmailAddress.objects.create(
        user=user,
        email=user.email,
        primary=True,
        verified=False,
    )
    request = rf.get("/api/users/me/")
    request.user = user

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 200
    assert user_has_verified_email(user) is False


def test_require_verified_email_ignores_anonymous_request(rf):
    request = rf.get("/api/contact/")
    request.user = SimpleNamespace(is_authenticated=False)

    response = RequireVerifiedEmailMiddleware(_ok_response)(request)

    assert response.status_code == 200


def _create_user(email, **extra_fields):
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_test"),
    ):
        return get_user_model().objects.create_user(email=email, **extra_fields)


def _ok_response(_request):
    return JsonResponse({"ok": True})
