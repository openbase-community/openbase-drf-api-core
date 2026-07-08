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
        "SOCIALACCOUNT_EMAIL_AUTHENTICATION": True,
        "SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT": True,
        "SOCIALACCOUNT_EMAIL_VERIFICATION": "none",
        "SOCIALACCOUNT_PROVIDERS": {"google": {"VERIFIED_EMAIL": True}},
        "OPENBASE_CODER_CLI_OAUTH_CLIENT_ID": "openbase-coder-cli",
    }
    package_settings = SimpleNamespace(
        ACCOUNT_EMAIL_VERIFICATION="none",
        SOCIALACCOUNT_EMAIL_AUTHENTICATION=False,
        SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT=False,
        SOCIALACCOUNT_EMAIL_VERIFICATION="mandatory",
        SOCIALACCOUNT_PROVIDERS={"google": {"VERIFIED_EMAIL": False}},
        OPENBASE_CODER_CLI_OAUTH_CLIENT_ID="package-client",
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["ACCOUNT_EMAIL_VERIFICATION"] == "mandatory"
    assert target_globals["SOCIALACCOUNT_EMAIL_AUTHENTICATION"] is True
    assert target_globals["SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT"] is True
    assert target_globals["SOCIALACCOUNT_EMAIL_VERIFICATION"] == "none"
    assert target_globals["SOCIALACCOUNT_PROVIDERS"] == {
        "google": {"VERIFIED_EMAIL": True}
    }
    assert target_globals["OPENBASE_CODER_CLI_OAUTH_CLIENT_ID"] == "package-client"


def test_package_settings_cannot_override_headless_auth_settings():
    target_globals = {
        "HEADLESS_ONLY": False,
    }
    package_settings = SimpleNamespace(
        HEADLESS_ONLY=True,
        COMMITLY_FRONTEND_BASE_URL="https://commitly.example.com",
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["HEADLESS_ONLY"] is False
    assert target_globals["COMMITLY_FRONTEND_BASE_URL"] == (
        "https://commitly.example.com"
    )


def test_package_settings_cannot_override_security_critical_settings():
    original_secret = "server-secret"  # noqa: S105
    target_globals = {
        "SECRET_KEY": original_secret,
        "REST_FRAMEWORK": {"DEFAULT_PERMISSION_CLASSES": ["...IsAuthenticated"]},
        "DEBUG": False,
        "ALLOWED_HOSTS": ["api.example.com"],
    }
    hostile_package = SimpleNamespace(
        SECRET_KEY="attacker-known-secret",  # noqa: S106
        HEADLESS_JWT_PRIVATE_KEY="exfiltrated",
        REST_FRAMEWORK={"DEFAULT_PERMISSION_CLASSES": ["...AllowAny"]},
        MIDDLEWARE=[],
        INSTALLED_APPS=["evil"],
        DATABASES={"default": {}},
        DEBUG=True,
        ALLOWED_HOSTS=["*"],
        STRIPE_SECRET_KEY="sk_attacker",  # noqa: S106
        AWS_SECRET_ACCESS_KEY="stolen",  # noqa: S106
    )

    merge_settings_from_module(hostile_package, target_globals)

    assert target_globals["SECRET_KEY"] == original_secret
    assert "HEADLESS_JWT_PRIVATE_KEY" not in target_globals
    assert target_globals["REST_FRAMEWORK"] == {
        "DEFAULT_PERMISSION_CLASSES": ["...IsAuthenticated"]
    }
    assert "MIDDLEWARE" not in target_globals
    assert "INSTALLED_APPS" not in target_globals
    assert "DATABASES" not in target_globals
    assert target_globals["DEBUG"] is False
    assert target_globals["ALLOWED_HOSTS"] == ["api.example.com"]
    assert "STRIPE_SECRET_KEY" not in target_globals
    assert "AWS_SECRET_ACCESS_KEY" not in target_globals


def test_package_settings_cannot_override_security_policy_prefixes():
    target_globals = {"SECURE_SSL_REDIRECT": True}
    package_settings = SimpleNamespace(
        SECURE_SSL_REDIRECT=False,
        SECURE_PROXY_SSL_HEADER=("X", "y"),
        SESSION_COOKIE_SECURE=False,
        CSRF_TRUSTED_ORIGINS=["https://evil.example.com"],
        CORS_ALLOW_ALL_ORIGINS=True,
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["SECURE_SSL_REDIRECT"] is True
    assert "SECURE_PROXY_SSL_HEADER" not in target_globals
    assert "SESSION_COOKIE_SECURE" not in target_globals
    assert "CSRF_TRUSTED_ORIGINS" not in target_globals
    assert "CORS_ALLOW_ALL_ORIGINS" not in target_globals


def test_package_settings_still_contribute_namespaced_and_secret_bearing_settings():
    # App packages legitimately ship their own namespaced settings, including
    # secret-bearing ones their own code reads; protection must not block these.
    target_globals: dict[str, object] = {}
    package_settings = SimpleNamespace(
        SUBSCRIPTION_TIERS={"pro": 6000},
        TAILSCALE_OAUTH_CLIENT_SECRET="tskey-secret",  # noqa: S106
        OPENBASE_LLM_OPENAI_API_KEY="sk-app-owned",
        DEVSPACE_IDLE_TIMEOUT_MINUTES=30,
        lowercase_ignored="skip",
    )

    merge_settings_from_module(package_settings, target_globals)

    assert target_globals["SUBSCRIPTION_TIERS"] == {"pro": 6000}
    assert target_globals["TAILSCALE_OAUTH_CLIENT_SECRET"] == "tskey-secret"  # noqa: S105
    assert target_globals["OPENBASE_LLM_OPENAI_API_KEY"] == "sk-app-owned"
    assert target_globals["DEVSPACE_IDLE_TIMEOUT_MINUTES"] == 30
    assert "lowercase_ignored" not in target_globals


def test_root_urlpatterns_load_from_entry_points(monkeypatch):
    installed_apps.get_root_urlpatterns.cache_clear()
    monkeypatch.setattr(
        installed_apps.importlib.metadata,
        "entry_points",
        lambda: FakeEntryPoints(
            {
                "api_core.root_urls": [
                    FakeEntryPoint(
                        lambda: [
                            path("webhook/", lambda _request: None, name="webhook")
                        ]
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
