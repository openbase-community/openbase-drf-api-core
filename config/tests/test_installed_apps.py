from types import SimpleNamespace

from config.installed_apps import merge_settings_from_module


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
