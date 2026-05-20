import os
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
import sentry_sdk

from config.installed_apps import get_installed_apps, load_all_package_settings
from config.logging import get_logging_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SITE_ID = 1 if DEBUG else None

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = (
    os.environ.get("ALLOWED_HOSTS", "").strip().split(",")
    if os.environ.get("ALLOWED_HOSTS")
    else []
)


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "channels",
    "storages",
    "rest_framework",
    "rest_framework.authtoken",
    "oauth2_provider",
    "corsheaders",
    "adrf",
    "drf_spectacular",
    "django.contrib.sites",
    "sites.apps.SitesConfig",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.headless",
    "allauth.usersessions",
    "users.apps.UsersConfig",
    "contact.apps.ContactConfig",
    "payment.apps.PaymentConfig",
    "teams.apps.TeamsConfig",
    *get_installed_apps(),
]

if DEBUG:
    staticfiles_index = INSTALLED_APPS.index("django.contrib.staticfiles")
    INSTALLED_APPS.insert(staticfiles_index, "whitenoise.runserver_nostatic")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "config.middlewares.admin_name_middleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# Add debug-only middleware
if DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    MIDDLEWARE.append("config.middlewares.AllowIframeMiddleware")

# CORS settings
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.global_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {"default": dj_database_url.config()}
DATABASES["default"]["CONN_MAX_AGE"] = 60

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

# AWS Configuration
AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")

if DEBUG:
    STATIC_URL = "/static/"
    STATIC_ROOT = BASE_DIR / "staticfiles"

    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"
    WHITENOISE_USE_FINDERS = True

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    AWS_S3_CUSTOM_DOMAIN = os.environ["AWS_S3_CUSTOM_DOMAIN"]
    AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]

    AWS_DEFAULT_ACL = "public-read"
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }
    AWS_LOCATION = "static"  # subdirectory in S3 for static files

    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"

    STORAGES = {
        "default": {
            "BACKEND": "config.storages.S3MediaStorage",
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
    }

STATICFILES_DIRS = [BASE_DIR / "static"]
EMAIL_BACKEND = "config.email.ResendEmailBackend"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Security
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # Caddy handles SSL termination
    SECURE_HSTS_SECONDS = 31536000

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO" if not DEBUG else "DEBUG")
LOGGING_BASE_APPS = [
    "config",
    "contact",
    "payment",
    "teams",
    "users",
]
LOGGING = get_logging_config(
    debug=DEBUG,
    log_level=LOG_LEVEL,
    base_apps=LOGGING_BASE_APPS,
)


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "allauth.headless.contrib.rest_framework.authentication.JWTTokenAuthentication",
        "allauth.headless.contrib.rest_framework.authentication.XSessionTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "DESCRIPTION": "API Documentation",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "DEFAULT_GENERATOR_CLASS": "config.spectacular_generators.TitleSettingGenerator",
    "COMPONENT_SPLIT_REQUEST": True,
}

ASGI_APPLICATION = "config.routing.application"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

AUTH_USER_MODEL = "users.User"

REDIS_URL = os.environ["REDIS_URL"]
if not DEBUG and REDIS_URL.startswith("rediss://"):
    REDIS_URL = f"{REDIS_URL}{'&' if '?' in REDIS_URL else '?'}ssl_cert_reqs=none"
REDIS_HOST = urlparse(REDIS_URL).hostname
REDIS_PORT = urlparse(REDIS_URL).port
BROKER_URL = REDIS_URL

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                (
                    {
                        "address": REDIS_URL,
                        "ssl_cert_reqs": None,
                    }
                    if not DEBUG
                    else (REDIS_HOST, REDIS_PORT)
                ),
            ],
        },
    },
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
OWNED_TWILIO_NUMBER = os.environ.get("OWNED_TWILIO_NUMBER")

NOTIFICATIONS_APPLE_TEAM_ID = os.environ.get("NOTIFICATIONS_APPLE_TEAM_ID")
NOTIFICATIONS_APPLE_AUTH_KEY_ID = os.environ.get("NOTIFICATIONS_APPLE_AUTH_KEY_ID")
NOTIFICATIONS_APPLE_P8_CONTENTS = os.environ.get(
    "NOTIFICATIONS_APPLE_P8_CONTENTS", ""
).replace("\\n", "\n")
NOTIFICATIONS_SANDBOX = os.environ.get("NOTIFICATIONS_SANDBOX", "0") == "1"

if not DEBUG:
    CSRF_TRUSTED_ORIGINS = [f"https://{domain}" for domain in ALLOWED_HOSTS]
    CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS.copy()
    CORS_ALLOWED_ORIGINS.insert(0, f"https://{AWS_S3_CUSTOM_DOMAIN}")
else:
    CSRF_TRUSTED_ORIGINS = [
        "http://localhost:3000",
        "http://0.0.0.0:8000",
        "http://localhost",
        "http://localhost:8080",
        "http://localhost:8081",
    ]
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://0.0.0.0:8000",
        "http://localhost",
        "http://localhost:8080",
        "http://localhost:8081",
    ]

_extra_csrf_origins = [
    origin.strip()
    for origin in os.environ.get("EXTRA_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
_extra_cors_origins = [
    origin.strip()
    for origin in os.environ.get("EXTRA_CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = list(CSRF_TRUSTED_ORIGINS) + _extra_csrf_origins
CORS_ALLOWED_ORIGINS = list(CORS_ALLOWED_ORIGINS) + _extra_cors_origins

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
CONTACT_NOTIFICATION_EMAIL = os.environ.get("CONTACT_NOTIFICATION_EMAIL")

APPLE_BUNDLE_ID = os.environ.get("APPLE_BUNDLE_ID")
APPLE_APP_APPLE_ID = os.environ.get("APPLE_APP_APPLE_ID")
APPLE_STOREKIT_KEY_ID = os.environ.get("APPLE_STOREKIT_KEY_ID")
APPLE_STOREKIT_ISSUER_ID = os.environ.get("APPLE_STOREKIT_ISSUER_ID")
APPLE_STOREKIT_P8_CONTENTS = os.environ.get("APPLE_STOREKIT_P8_CONTENTS")

ADMIN_SUFFIX = os.environ["DJANGO_ADMIN_SUFFIX"] if not DEBUG else ""

SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )

# Add these settings near the authentication-related settings
AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

# AllAuth settings
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True

if not DEBUG:
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

ACCOUNT_ADAPTER = "config.allauth_adapter.AccountAdapter"
HEADLESS_ADAPTER = "config.allauth_adapter.HeadlessAdapter"

HEADLESS_ENABLED = True
HEADLESS_ONLY = True
HEADLESS_TOKEN_STRATEGY = "config.jwt.OpenbaseJWTTokenStrategy"  # noqa: S105
HEADLESS_JWT_PRIVATE_KEY = os.environ["HEADLESS_JWT_PRIVATE_KEY"].replace("\\n", "\n")
if os.environ.get("HEADLESS_JWT_ISSUER"):
    HEADLESS_JWT_ISSUER = os.environ["HEADLESS_JWT_ISSUER"]
HEADLESS_JWT_AUDIENCE = os.environ.get("HEADLESS_JWT_AUDIENCE", "openbase-coder-cli")
HEADLESS_JWT_ACCESS_TOKEN_EXPIRES_IN = 300  # 5 minutes
HEADLESS_JWT_REFRESH_TOKEN_EXPIRES_IN = 86400 * 7  # 7 days
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": "/account/verify-email/{key}",
    "account_reset_password": "/account/password/reset",
    "account_reset_password_from_key": "/account/password/reset/key/{key}",
    "account_signup": "/account/signup",
    "socialaccount_login_error": "/account/provider/callback",
}

# Optional but recommended for email-only setup
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USER_DISPLAY = lambda user: user.email  # noqa: E731

SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

LOGIN_URL = "/account/login"
LOGIN_REDIRECT_URL = "/"  # Where to redirect after login
LOGOUT_REDIRECT_URL = "/"  # Where to redirect after logout

BILLING_MAX_PROJECTS_PER_USER = int(os.getenv("BILLING_MAX_PROJECTS_PER_USER", "1"))
BILLING_MAX_LIVEKIT_TOKENS_PER_DAY = int(
    os.getenv("BILLING_MAX_LIVEKIT_TOKENS_PER_DAY", "100")
)


# Load settings.py from each app if it exists
load_all_package_settings(globals())
