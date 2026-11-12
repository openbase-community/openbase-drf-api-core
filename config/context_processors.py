from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site


def global_settings(request):
    current_site = get_current_site(request)
    product_name = current_site.name if current_site is not None else ""
    return {
        "product_name": product_name,
        "password_auth_enabled": settings.PASSWORD_AUTH_ENABLED,
    }
