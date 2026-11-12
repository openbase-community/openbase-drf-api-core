import inspect

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.contrib.sites.shortcuts import get_current_site
from django.db import models
from django.http import HttpRequest, HttpResponseForbidden

from sites.models import SiteAttributes


class DynamicAdminSite(admin.AdminSite):
    def login(self, request: HttpRequest, extra_context=None):
        """Sign staff in through the product's own login, not the admin form.

        The admin form only knows passwords, and password authentication is
        retired (``PASSWORD_AUTH_ENABLED``). The frontend login at
        ``settings.LOGIN_URL`` is served from the same host, so its session
        cookie is the admin's session cookie: staff sign in with a code or a
        social provider there and come straight back to the page they wanted.
        """
        if settings.PASSWORD_AUTH_ENABLED:
            return super().login(request, extra_context)
        if request.user.is_authenticated:
            if self.has_permission(request):
                return super().login(request, extra_context)
            return HttpResponseForbidden(
                "This account is signed in but is not staff, so it cannot use the admin."
            )
        next_url = request.GET.get("next") or request.get_full_path()
        return redirect_to_login(next_url, login_url=settings.LOGIN_URL)

    def get_app_list(self, request: HttpRequest, *args, **kwargs):
        """
        Return a list of applications and models that are available for the
        current site.
        """
        app_list = super().get_app_list(request, *args, **kwargs)
        current_site = get_current_site(request)

        if not current_site:
            return app_list

        site_attributes = SiteAttributes.objects.filter(site=current_site).first()
        if not site_attributes or not site_attributes.admin_app_labels:
            return app_list

        allowed_app_labels = {
            app_label
            for app_label in site_attributes.admin_app_labels
            if isinstance(app_label, str) and app_label.strip()
        }
        return [
            app for app in app_list if app["app_label"] in allowed_app_labels
        ]


def auto_register_models(app_models):
    """
    Automatically register all Django models from the models module.
    """
    # Get all members of the models module
    model_classes = inspect.getmembers(app_models, inspect.isclass)

    # Filter to only Django models (exclude imported models like User)
    django_models = []
    for name, model_class in model_classes:
        # Check if it's a Django model and defined in this app (not imported)
        if (
            issubclass(model_class, models.Model)
            and model_class.__module__ == app_models.__name__
            and model_class != models.Model  # Exclude the base Model class itself
        ):
            django_models.append((name, model_class))

    # Register each model with the admin
    for _, model_class in django_models:
        admin.site.register(model_class)


# Rebind Django's default admin site so existing registrations keep working.
admin.site.__class__ = DynamicAdminSite
site = admin.site
