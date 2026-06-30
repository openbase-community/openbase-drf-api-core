from asgiref.sync import (
    iscoroutinefunction,
    sync_to_async,
)
from django.conf import settings
from django.contrib import admin
from django.contrib.sites.models import SITE_CACHE
from django.contrib.sites.shortcuts import get_current_site
from django.http import JsonResponse
from django.utils.decorators import sync_and_async_middleware

from config.email_verification import (
    ensure_user_email_verified,
    user_has_verified_email,
)


class RequireVerifiedEmailMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            request.path.startswith("/api/")
            and not self._is_exempt_path(request.path)
            and user
            and user.is_authenticated
            and not user_has_verified_email(user)
        ):
            if settings.REQUIRE_VERIFIED_EMAIL_AUTO_VERIFY_AUTHENTICATED:
                ensure_user_email_verified(user)
                return self.get_response(request)
            return JsonResponse(
                {
                    "code": "email_not_verified",
                    "detail": settings.REQUIRE_VERIFIED_EMAIL_MESSAGE,
                },
                status=403,
            )
        return self.get_response(request)

    def _is_exempt_path(self, path: str) -> bool:
        return any(
            path.startswith(prefix)
            for prefix in settings.REQUIRE_VERIFIED_EMAIL_EXEMPT_PATH_PREFIXES
        )


def _set_admin_headers(site):
    if site is not None:
        admin.site.site_header = f"{site.name} Admin"
        admin.site.site_title = f"{site.name} Admin"


@sync_and_async_middleware
def admin_name_middleware(get_response):
    if iscoroutinefunction(get_response):

        async def async_impl(request):
            host = request.get_host()
            if host in SITE_CACHE:
                site = SITE_CACHE[host]
            else:
                site = await sync_to_async(get_current_site)(request)
            _set_admin_headers(site)
            response = await get_response(request)
            return response

        return async_impl

    def sync_impl(request):
        site = get_current_site(request)
        _set_admin_headers(site)
        response = get_response(request)
        return response

    return sync_impl


class AllowIframeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only apply for localhost
        if request.get_host().startswith("localhost"):
            response.headers["X-Frame-Options"] = "ALLOWALL"

        return response
