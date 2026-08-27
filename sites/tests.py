from types import SimpleNamespace

import httpx
import pytest
from allauth.socialaccount.models import SocialApp
from asgiref.sync import async_to_sync
from django.contrib.sites.models import Site
from django.contrib.sites.shortcuts import get_current_site
from django.core.management import call_command
from django.test import override_settings
from django.urls import path

from config.admin import site as dynamic_admin_site
from contact.models import ContactSubmission
from sites.models import SiteAttributes
from sites.views import serve_index

urlpatterns = [
    path("admin/", dynamic_admin_site.urls),
]


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_site_cache():
    yield
    Site.objects.clear_cache()


@override_settings(
    ROOT_URLCONF="sites.tests",
    ALLOWED_HOSTS=["admin.example.com"],
    SITE_ID=None,
)
def test_get_app_list_filters_to_allowed_site_app_labels(rf):
    site = Site.objects.create(domain="admin.example.com", name="Admin Example")
    SiteAttributes.objects.create(site=site, admin_app_labels=["users", "teams"])

    request = rf.get("/admin/", HTTP_HOST=site.domain)
    request.user = _AdminTestUser()

    app_list = dynamic_admin_site.get_app_list(request)

    assert [app["app_label"] for app in app_list] == ["teams", "users"]


@override_settings(
    ROOT_URLCONF="sites.tests",
    ALLOWED_HOSTS=["admin.example.com"],
    SITE_ID=None,
)
def test_get_app_list_shows_all_apps_when_site_has_no_restrictions(rf):
    site = Site.objects.create(domain="admin.example.com", name="Admin Example")
    SiteAttributes.objects.create(site=site, admin_app_labels=[])

    request = rf.get("/admin/", HTTP_HOST=site.domain)
    request.user = _AdminTestUser()

    app_labels = {app["app_label"] for app in dynamic_admin_site.get_app_list(request)}

    assert {"users", "teams", "payment"}.issubset(app_labels)


@override_settings(
    ALLOWED_HOSTS=["localhost", "other.example.com"], DEBUG=True, SITE_ID=1
)
def test_debug_site_id_always_uses_default_site(rf):
    call_command("ensure_default_sites")
    localhost_site = Site.objects.get(pk=1)
    Site.objects.create(domain="other.example.com", name="Other")

    request = rf.get("/", HTTP_HOST="other.example.com")

    current_site = get_current_site(request)

    assert current_site.pk == localhost_site.pk
    assert current_site.domain == "localhost"


def test_ensure_default_sites_preserves_existing_non_default_sites():
    local_network_site = Site.objects.create(
        domain="0.0.0.0:8000", name="Local Network"
    )
    other_site = Site.objects.create(domain="other.example.com", name="Other")

    call_command("ensure_default_sites")

    localhost_sites = list(
        Site.objects.filter(domain="localhost").values_list("id", flat=True)
    )

    assert localhost_sites == [1]
    assert Site.objects.filter(
        id=local_network_site.id,
        domain="0.0.0.0:8000",
        name="Local Network",
    ).exists()
    assert Site.objects.filter(
        id=other_site.id,
        domain="other.example.com",
        name="Other",
    ).exists()
    assert SiteAttributes.objects.filter(site_id=1).exists()


def test_ensure_default_sites_is_idempotent_when_localhost_site_already_exists():
    Site.objects.update_or_create(
        id=1,
        defaults={"domain": "example.com", "name": "example.com"},
    )
    existing_localhost_site = Site.objects.create(
        domain="localhost",
        name="Existing Localhost",
    )
    SiteAttributes.objects.create(
        site=existing_localhost_site,
        from_email="team@localhost.test",
    )
    ContactSubmission.objects.create(
        site=existing_localhost_site,
        email="ada@example.com",
        message="Testing idempotence.",
    )
    social_app = SocialApp.objects.create(
        provider="google",
        name="Google",
        client_id="client-id",
        secret="client-secret",
        key="",
        provider_id="",
        settings={},
    )
    social_app.sites.add(existing_localhost_site)

    call_command("ensure_default_sites")
    call_command("ensure_default_sites")

    default_site = Site.objects.get(pk=1)

    assert default_site.domain == "localhost"
    assert default_site.name == "localhost"
    assert list(
        Site.objects.filter(domain="localhost").values_list("id", flat=True)
    ) == [1]
    assert not Site.objects.filter(pk=existing_localhost_site.pk).exists()
    assert SiteAttributes.objects.filter(
        site=default_site,
        from_email="team@localhost.test",
    ).exists()
    assert ContactSubmission.objects.filter(
        site=default_site,
        email="ada@example.com",
    ).exists()
    assert social_app.sites.filter(pk=default_site.pk).exists()


def test_ensure_default_sites_adds_runtime_domains():
    call_command(
        "ensure_default_sites",
        "--domain",
        "app.example.com",
        "--domain",
        "api.example.com",
    )

    assert Site.objects.filter(
        domain="app.example.com", name="app.example.com"
    ).exists()
    assert Site.objects.filter(
        domain="api.example.com", name="api.example.com"
    ).exists()
    assert SiteAttributes.objects.filter(site__domain="app.example.com").exists()
    assert SiteAttributes.objects.filter(site__domain="api.example.com").exists()


@override_settings(ALLOWED_HOSTS=["app.example.com", "api.example.com", "localhost"])
def test_ensure_default_sites_reads_allowed_hosts_from_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com,api.example.com,localhost")

    call_command("ensure_default_sites", "--from-allowed-hosts")

    assert Site.objects.filter(
        domain="app.example.com", name="app.example.com"
    ).exists()
    assert Site.objects.filter(
        domain="api.example.com", name="api.example.com"
    ).exists()
    assert (
        not Site.objects.filter(domain="localhost", name="localhost")
        .exclude(pk=1)
        .exists()
    )


def test_sync_deployment_site_creates_site_and_attributes():
    call_command(
        "sync_deployment_site",
        "--domain",
        "deploy-abc.openbase.app",
        "--s3-custom-domain",
        "d111111abcdef8.cloudfront.net",
        "--s3-frontend-folder",
        "sites/deploy-abc",
    )

    site = Site.objects.get(domain="deploy-abc.openbase.app")
    attributes = SiteAttributes.objects.get(site=site)

    assert site.name == "deploy-abc.openbase.app"
    assert attributes.s3_custom_domain == "d111111abcdef8.cloudfront.net"
    assert attributes.s3_frontend_folder == "sites/deploy-abc"
    assert attributes.from_email == "team@deploy-abc.openbase.app"


def test_sync_deployment_site_updates_existing_attributes():
    site = Site.objects.create(domain="deploy-abc.openbase.app", name="Old Name")
    SiteAttributes.objects.create(
        site=site,
        s3_custom_domain="old.cloudfront.net",
        s3_frontend_folder="old-folder",
        from_email="team@old.example.com",
    )

    call_command(
        "sync_deployment_site",
        "--domain",
        "deploy-abc.openbase.app",
        "--s3-custom-domain",
        "new.cloudfront.net",
        "--s3-frontend-folder",
        "sites/new-folder",
    )

    site.refresh_from_db()
    attributes = SiteAttributes.objects.get(site=site)

    assert site.name == "deploy-abc.openbase.app"
    assert attributes.s3_custom_domain == "new.cloudfront.net"
    assert attributes.s3_frontend_folder == "sites/new-folder"
    assert attributes.from_email == "team@deploy-abc.openbase.app"


def test_sync_deployment_site_provisions_configured_oauth_for_its_domain(monkeypatch):
    monkeypatch.setenv(
        "GOOGLE_OAUTH_CREDENTIALS_JSON",
        '{"web": {"client_id": "client-id", "client_secret": "client-secret"}}',
    )

    call_command("sync_deployment_site", "--domain", "deploy-abc.openbase.app")

    site = Site.objects.get(domain="deploy-abc.openbase.app")
    social_app = SocialApp.objects.get(provider="google")
    # The provider must attach to THIS deployment's site, not the default
    # localhost site, so allauth can resolve it by request host in production.
    assert list(social_app.sites.values_list("id", flat=True)) == [site.id]


def test_sync_deployment_site_skips_oauth_without_credentials(monkeypatch):
    for env_prefix in ("GOOGLE", "GITHUB", "APPLE"):
        monkeypatch.delenv(f"{env_prefix}_OAUTH_CREDENTIALS_JSON", raising=False)

    call_command("sync_deployment_site", "--domain", "deploy-abc.openbase.app")

    assert not SocialApp.objects.exists()


def test_serve_index_returns_gateway_timeout_when_index_fetch_times_out(
    rf, monkeypatch
):
    async def current_site_attributes(request):
        return SimpleNamespace(
            s3_custom_domain="d111111abcdef8.cloudfront.net",
            s3_frontend_folder="sites/deploy-abc",
        )

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url):
            request = httpx.Request("GET", url)
            raise httpx.ReadTimeout("timed out", request=request)

    class Cache:
        async def aget(self, key):
            return None

        async def aset(self, key, value, timeout):
            return None

    monkeypatch.setattr("sites.views.aget_current_site_attributes", current_site_attributes)
    monkeypatch.setattr("sites.views.cache", Cache())
    monkeypatch.setattr("sites.views.httpx.AsyncClient", lambda: Client())

    request = rf.get("/", HTTP_ACCEPT="text/html")

    response = async_to_sync(serve_index)(request, "")

    assert response.status_code == 504
    assert b"Timed out fetching index.html from S3" in response.content


class _AdminTestUser:
    is_active = True
    is_staff = True
    is_superuser = True

    def has_module_perms(self, app_label):
        return True

    def has_perm(self, perm, obj=None):
        return True
