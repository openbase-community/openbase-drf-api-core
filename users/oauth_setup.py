"""Shared base for the ``ensure_<provider>_oauth`` management commands.

Nothing here is specific to any provider or deployment: a command subclass
declares the provider id, a display label, and an environment-variable prefix,
and the base class resolves the target sites, parses the credentials, and
upserts the ``SocialApp`` row.

Providers are strictly opt-in. With no credentials supplied (and non-interactive
mode), no ``SocialApp`` is created and no provider button ever appears — so
adding a new ``ensure_<provider>_oauth`` command is backwards compatible for any
consuming project that does not configure that provider.
"""

import json
import os

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.management import BaseCommand, CommandError


def parse_client_credentials(raw, *, provider_label):
    """Parse ``client_id``/``client_secret`` from a credentials JSON string.

    Accepts both a flat ``{"client_id", "client_secret"}`` object (GitHub's
    format) and a Google-style ``{"web": {...}}`` wrapper, so a single helper
    covers every provider.
    """
    try:
        credentials = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{provider_label} OAuth credentials must be valid JSON."
        raise CommandError(msg) from exc
    if not isinstance(credentials, dict):
        msg = f"{provider_label} OAuth credentials must be a JSON object."
        raise CommandError(msg)

    config = (
        credentials["web"] if isinstance(credentials.get("web"), dict) else credentials
    )
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not client_id or not client_secret:
        msg = f"{provider_label} OAuth credentials must include client_id and client_secret."
        raise CommandError(msg)
    return client_id, client_secret


def upsert_social_app(*, provider, name, client_id, client_secret, sites):
    """Create or update the ``SocialApp`` for ``provider`` and attach ``sites``."""
    app = SocialApp.objects.filter(
        provider=provider,
        client_id=client_id,
        secret=client_secret,
    ).first()
    if app is None:
        app = SocialApp.objects.create(
            provider=provider,
            name=name,
            client_id=client_id,
            secret=client_secret,
            key="",
            provider_id="",
            settings={},
        )
    elif app.name != name:
        app.name = name
        app.save(update_fields=["name"])

    existing_app_site_ids = set(app.sites.values_list("id", flat=True))
    missing_sites = [site for site in sites if site.id not in existing_app_site_ids]
    if missing_sites:
        app.sites.add(*missing_sites)
    return app


class EnsureOAuthSocialAppCommand(BaseCommand):
    """Opt-in seeding of one social provider's ``SocialApp`` from the environment.

    Subclasses declare::

        provider = "github"            # allauth provider id
        provider_label = "GitHub"      # human-readable name for messages
        env_prefix = "GITHUB_OAUTH"    # prefix for the environment variables

    The derived environment variables are ``<prefix>_CREDENTIALS_JSON``,
    ``<prefix>_SITE_DOMAINS`` (comma-separated), and ``<prefix>_SITE_DOMAIN``.
    """

    provider = None
    provider_label = None
    env_prefix = None

    def add_arguments(self, parser):
        parser.add_argument(
            "--credentials-json",
            help=(
                f"{self.provider_label} OAuth credentials JSON. "
                "If omitted, the command prompts for it."
            ),
        )
        parser.add_argument(
            "--name",
            default="My App",
            help="Display name for the created SocialApp.",
        )
        parser.add_argument(
            "--site-domain",
            action="append",
            dest="site_domains",
            help=(
                "Attach the SocialApp to the site with this domain. "
                "Can be supplied multiple times."
            ),
        )
        parser.add_argument(
            "--non-interactive",
            action="store_true",
            help="Skip prompting and exit successfully when credentials are unavailable.",
        )

    def handle(self, *args, **options):
        sites = self._resolve_target_sites(options["site_domains"])
        if self._sites_already_configured(sites):
            self.stdout.write(
                f"{self.provider_label} OAuth already configured for requested site(s), skipping..."
            )
            return

        credentials_raw = self._read_credentials(options)
        if credentials_raw is None:
            return

        client_id, client_secret = parse_client_credentials(
            credentials_raw, provider_label=self.provider_label
        )
        upsert_social_app(
            provider=self.provider,
            name=options["name"],
            client_id=client_id,
            client_secret=client_secret,
            sites=sites,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Successfully configured {self.provider_label} OAuth.")
        )

    def _resolve_target_sites(self, site_domains):
        """Return the ``Site`` rows the provider should attach to.

        Domains come from the explicit ``--site-domain`` args plus the derived
        environment variables. With no domains requested, falls back to the
        default site (id=1), matching allauth's DEBUG ``SITE_ID``.
        """
        site_domains = list(site_domains or [])
        env_site_domains = os.environ.get(f"{self.env_prefix}_SITE_DOMAINS", "")
        if env_site_domains:
            site_domains.extend(
                domain.strip()
                for domain in env_site_domains.split(",")
                if domain.strip()
            )
        env_site_domain = os.environ.get(f"{self.env_prefix}_SITE_DOMAIN")
        if env_site_domain:
            site_domains.append(env_site_domain.strip())

        if site_domains:
            sites = list(Site.objects.filter(domain__in=site_domains))
            missing_site_domains = sorted(
                set(site_domains) - {site.domain for site in sites}
            )
            if missing_site_domains:
                msg = (
                    f"Could not find site(s) for {self.provider_label} OAuth: "
                    + ", ".join(missing_site_domains)
                )
                raise CommandError(msg)
            return sites

        sites = list(Site.objects.filter(id=1))
        if len(sites) != 1:
            msg = (
                "Default site is missing. Run ensure_default_sites before "
                f"configuring {self.provider_label} OAuth."
            )
            raise CommandError(msg)
        return sites

    def _sites_already_configured(self, sites):
        """True when every requested site already has this provider's SocialApp."""
        existing_site_domains = {
            domain
            for domain in SocialApp.objects.filter(
                provider=self.provider, sites__in=sites
            )
            .values_list("sites__domain", flat=True)
            .distinct()
        }
        requested_site_domains = {site.domain for site in sites}
        return requested_site_domains.issubset(existing_site_domains)

    def _read_credentials(self, options):
        """Return the raw credentials JSON, or ``None`` when opting out."""
        credentials_raw = options["credentials_json"] or os.environ.get(
            f"{self.env_prefix}_CREDENTIALS_JSON"
        )
        if credentials_raw is not None:
            return credentials_raw

        if options["non_interactive"]:
            self.stdout.write(
                f"No {self.provider_label} OAuth configuration found, "
                "skipping in non-interactive mode..."
            )
            return None

        self.stdout.write(f"No {self.provider_label} OAuth configuration found.")
        self.stdout.write(
            f"Paste your {self.provider_label} OAuth credentials JSON, "
            "or press Enter on an empty line to skip:"
        )
        credentials_raw = input().strip()
        if not credentials_raw:
            self.stdout.write(f"Skipping {self.provider_label} OAuth configuration...")
            return None
        return credentials_raw
