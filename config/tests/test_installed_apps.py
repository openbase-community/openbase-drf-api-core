from types import SimpleNamespace

from django.urls import path

from config import installed_apps
from config.installed_apps import merge_settings_from_module


class FakeEntryPoints:
    def __init__(self, groups):
        self.groups = groups

    def select(self, *, group):
        return self.groups.get(group, [])


class FakeEntryPoint:
    def __init__(self, value):
        self.value = value

    def load(self):
        return self.value


def test_package_settings_cannot_override_core_account_verification():
    target_globals = {
        "ACCOUNT_EMAIL_VERIFICATION": "mandatory",
        "OPENBASE_CODER_CLI_OAUTH_CLIENT_ID": "openbase-coder-cli",
    }
    package_settings = SimpleNamespace(
        ACCOUNT_EMAIL_VERIFICATION="none",
        OPENBASE_CODER_CLI_OAUTH_CLIENT_ID="package-client",
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["ACCOUNT_EMAIL_VERIFICATION"] == "mandatory"
    assert target_globals["OPENBASE_CODER_CLI_OAUTH_CLIENT_ID"] == "package-client"


def test_package_settings_cannot_override_headless_auth_settings():
    target_globals = {
        "HEADLESS_ONLY": True,
    }
    package_settings = SimpleNamespace(
        HEADLESS_ONLY=False,
        COMMITLY_FRONTEND_BASE_URL="https://commitly.example.com",
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["HEADLESS_ONLY"] is True
    assert target_globals["COMMITLY_FRONTEND_BASE_URL"] == (
        "https://commitly.example.com"
    )


def test_root_urlpatterns_load_from_entry_points(monkeypatch):
    installed_apps.get_root_urlpatterns.cache_clear()
    monkeypatch.setattr(
        installed_apps.importlib.metadata,
        "entry_points",
        lambda: FakeEntryPoints(
            {
                "api_core.root_urls": [
                    FakeEntryPoint(
                        lambda: [path("webhook/", lambda _request: None, name="webhook")]
                    )
                ]
            }
        ),
    )

    try:
        urlpatterns = installed_apps.get_root_urlpatterns()
    finally:
        installed_apps.get_root_urlpatterns.cache_clear()

    assert len(urlpatterns) == 1
    assert urlpatterns[0].name == "webhook"
