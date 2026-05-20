import inspect

from django.contrib import admin
from django.contrib.sites.shortcuts import get_current_site
from django.db import models
from django.http import HttpRequest

from sites.models import SiteAttributes


class DynamicAdminSite(admin.AdminSite):
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
