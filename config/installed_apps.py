import functools
import importlib.metadata

PROTECTED_PACKAGE_SETTINGS = {
    "ACCOUNT_ADAPTER",
    "ACCOUNT_EMAIL_VERIFICATION",
    "ACCOUNT_LOGIN_METHODS",
    "ACCOUNT_SIGNUP_FIELDS",
    "ACCOUNT_UNIQUE_EMAIL",
    "ACCOUNT_USER_MODEL_EMAIL_FIELD",
    "ACCOUNT_USER_MODEL_USERNAME_FIELD",
    "AUTHENTICATION_BACKENDS",
    "HEADLESS_ADAPTER",
    "HEADLESS_ENABLED",
    "HEADLESS_FRONTEND_URLS",
    "HEADLESS_JWT_AUDIENCE",
    "HEADLESS_JWT_ISSUER",
    "HEADLESS_ONLY",
    "HEADLESS_TOKEN_STRATEGY",
}


@functools.cache
def get_installed_apps() -> list[str]:
    """Retrieve Django installed apps from registered entry points."""
    apps = []
    entry_points = importlib.metadata.entry_points()

    for entry_point in entry_points.select(group="api_core.installed_apps"):
        app_list_func = entry_point.load()
        if callable(app_list_func):
            apps.extend(app_list_func())

    return apps


@functools.cache
def get_root_urlpatterns() -> list:
    """Retrieve root URL patterns from registered entry points."""
    urlpatterns = []
    entry_points = importlib.metadata.entry_points()

    for entry_point in entry_points.select(group="api_core.root_urls"):
        url_list_func = entry_point.load()
        if callable(url_list_func):
            urlpatterns.extend(url_list_func())

    return urlpatterns


def merge_settings_from_module(mod, target_globals):
    names = getattr(mod, "__all__", None) or dir(mod)
    for name in names:
        # copy only public, UPPERCASE names (typical Django convention)
        if (
            not name.startswith("_")
            and name.isupper()
            and name not in PROTECTED_PACKAGE_SETTINGS
        ):
            target_globals[name] = getattr(mod, name)


def load_all_package_settings(target_globals):
    """Load settings from registered settings entry points."""
    entry_points = importlib.metadata.entry_points()
    for entry_point in entry_points.select(group="api_core.settings"):
        mod = entry_point.load()
        merge_settings_from_module(mod, target_globals)
