import functools
import importlib.metadata

import structlog

logger = structlog.get_logger(__name__)

# Settings that a hosted app package must never override. api-core owns the
# security posture of the shared multi-app server; an app package is a trust
# boundary that may *contribute* its own (additive) settings but cannot silently
# redefine the secret material, auth/permission pipeline, data layer, host/origin
# policy, or app/URL wiring that protect every tenant on the box. A package that
# could set e.g. REST_FRAMEWORK's DEFAULT_PERMISSION_CLASSES or exfiltrate
# SECRET_KEY/HEADLESS_JWT_PRIVATE_KEY would own the whole server.
PROTECTED_PACKAGE_SETTINGS = {
    # allauth / headless identity (issuer, adapters, token strategy)
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
    # secret material / signing keys / cloud credentials
    "SECRET_KEY",
    "SECRET_KEY_FALLBACKS",
    "HEADLESS_JWT_PRIVATE_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    # data layer
    "DATABASES",
    "DATABASE_ROUTERS",
    "CACHES",
    # auth / permission / request pipeline
    "MIDDLEWARE",
    "REST_FRAMEWORK",
    "PASSWORD_HASHERS",
    "AUTH_PASSWORD_VALIDATORS",
    # app & URL wiring
    "INSTALLED_APPS",
    "ROOT_URLCONF",
    "WSGI_APPLICATION",
    "ASGI_APPLICATION",
    # host / debug / payments / storage / mail / logging
    "DEBUG",
    "ALLOWED_HOSTS",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STORAGES",
    "DEFAULT_FILE_STORAGE",
    "STATICFILES_STORAGE",
    "EMAIL_BACKEND",
    "LOGGING",
    "LOGGING_CONFIG",
}

# Whole setting families that are global security policy for the shared site.
# App packages define their own namespaced settings (e.g. TAILSCALE_*,
# OPENBASE_LLM_*), so protection is by exact name or these core prefixes only —
# never by substring, since app packages legitimately ship their own
# secret-bearing settings such as OPENBASE_LLM_OPENAI_API_KEY.
PROTECTED_PACKAGE_SETTING_PREFIXES = ("SECURE_", "SESSION_", "CSRF_", "CORS_")


def _is_protected_setting(name: str) -> bool:
    return name in PROTECTED_PACKAGE_SETTINGS or name.startswith(
        PROTECTED_PACKAGE_SETTING_PREFIXES
    )


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
        if name.startswith("_") or not name.isupper():
            continue
        if _is_protected_setting(name):
            # Refuse the override and make the attempt visible: a hosted app
            # package trying to redefine core security settings is either a bug
            # or a supply-chain attack, and silently dropping it hides both.
            logger.warning(
                "ignored_protected_package_setting",
                setting=name,
                module=getattr(mod, "__name__", repr(mod)),
            )
            continue
        target_globals[name] = getattr(mod, name)


def load_all_package_settings(target_globals):
    """Load settings from registered settings entry points."""
    entry_points = importlib.metadata.entry_points()
    for entry_point in entry_points.select(group="api_core.settings"):
        mod = entry_point.load()
        merge_settings_from_module(mod, target_globals)
