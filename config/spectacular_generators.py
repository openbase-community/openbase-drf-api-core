import os

from django.contrib.sites.models import Site
from drf_spectacular.generators import SchemaGenerator

DEFAULT_SCHEMA_SITE_NAME = "OpenBase"


def _schema_site_name(request) -> str:
    if request is None:
        return os.environ.get("OPENBASE_API_SCHEMA_SITE_NAME", DEFAULT_SCHEMA_SITE_NAME)

    try:
        return Site.objects.get_current(request).name
    except Site.DoesNotExist:
        return DEFAULT_SCHEMA_SITE_NAME


class TitleSettingGenerator(SchemaGenerator):
    def get_schema(self, request=None, public: bool = False):  # noqa: FBT001, FBT002
        full_schema = super().get_schema(request, public)
        if full_schema is None:
            return None

        site_name = _schema_site_name(request)
        info = dict(full_schema.get("info", {}))
        info["title"] = f"{site_name} API Schemas"
        info["description"] = f"Generated schemas for {site_name}"
        info.setdefault("version", "1.0.0")
        full_schema["info"] = info
        return full_schema
