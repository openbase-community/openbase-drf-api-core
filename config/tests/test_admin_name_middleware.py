from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.http import JsonResponse

from config.middlewares import admin_name_middleware


def test_admin_name_middleware_skips_site_lookup_for_async_api_request(rf):
    request = rf.get("/api/csrf/", HTTP_HOST="unknown.example.com")

    with patch(
        "config.middlewares.get_current_site",
        side_effect=AssertionError("site lookup should be admin-only"),
    ):
        response = async_to_sync(admin_name_middleware(_async_ok_response))(request)

    assert response.status_code == 200


async def _async_ok_response(_request):
    return JsonResponse({"ok": True})
