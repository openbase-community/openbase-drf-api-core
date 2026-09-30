import asyncio
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.sites.models import Site
from django.http import JsonResponse
from django.test import override_settings

from config.middlewares import admin_name_middleware


def test_admin_name_middleware_skips_site_lookup_for_async_api_request(rf):
    request = rf.get("/api/csrf/", HTTP_HOST="unknown.example.com")

    with patch(
        "config.middlewares.get_current_site",
        side_effect=AssertionError("site lookup should be admin-only"),
    ):
        response = async_to_sync(admin_name_middleware(_async_ok_response))(request)

    assert response.status_code == 200


def test_admin_name_middleware_treats_async_cancel_as_client_disconnect(rf):
    request = rf.get("/_allauth/app/v1/config", HTTP_HOST="unknown.example.com")

    response = async_to_sync(admin_name_middleware(_async_cancelled_response))(request)

    assert response.status_code == 499


@override_settings(DEBUG=True)
def test_admin_name_middleware_tolerates_missing_site_for_sync_admin_request(rf):
    request = rf.get("/admin/", HTTP_HOST="unknown.example.com")

    with (
        patch(
            "config.middlewares.get_current_site",
            side_effect=Site.DoesNotExist,
        ),
        patch("config.middlewares._set_admin_headers") as set_admin_headers,
    ):
        response = admin_name_middleware(_ok_response)(request)

    assert response.status_code == 200
    set_admin_headers.assert_called_once_with(None)


@override_settings(DEBUG=True)
def test_admin_name_middleware_tolerates_missing_site_for_async_admin_request(rf):
    request = rf.get("/admin/", HTTP_HOST="unknown.example.com")

    with (
        patch(
            "config.middlewares.get_current_site",
            side_effect=Site.DoesNotExist,
        ),
        patch("config.middlewares._set_admin_headers") as set_admin_headers,
    ):
        response = async_to_sync(admin_name_middleware(_async_ok_response))(request)

    assert response.status_code == 200
    set_admin_headers.assert_called_once_with(None)


def _ok_response(_request):
    return JsonResponse({"ok": True})


async def _async_ok_response(_request):
    return JsonResponse({"ok": True})


async def _async_cancelled_response(_request):
    raise asyncio.CancelledError
