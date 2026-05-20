import json
import os

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.management import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Ensure a Google SocialApp exists for the default development sites."

    def add_arguments(self, parser):
        parser.add_argument(
            "--credentials-json",
            help="Google OAuth credentials JSON. If omitted, the command prompts for it.",
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
                "Attach the Google SocialApp to the site with this domain. "
                "Can be supplied multiple times."
            ),
        )
        parser.add_argument(
            "--non-interactive",
            action="store_true",
            help="Skip prompting and exit successfully when credentials are unavailable.",
        )

    def handle(self, *args, **options):
        sites = self._get_target_sites(options)
        existing_site_domains = {
            domain
            for domain in SocialApp.objects.filter(provider="google", sites__in=sites)
            .values_list("sites__domain", flat=True)
            .distinct()
        }
        requested_site_domains = {site.domain for site in sites}
        if requested_site_domains.issubset(existing_site_domains):
            self.stdout.write(
                "Google OAuth already configured for requested site(s), skipping..."
            )
            return

        credentials_raw = options["credentials_json"] or os.environ.get(
            "GOOGLE_OAUTH_CREDENTIALS_JSON"
        )
        if credentials_raw is None:
            if options["non_interactive"]:
                self.stdout.write(
                    "No Google OAuth configuration found, skipping in non-interactive mode..."
                )
                return

            self.stdout.write("No Google OAuth configuration found.")
            self.stdout.write(
                "Paste your Google OAuth credentials JSON, or press Enter on an empty line to skip:"
            )
            credentials_raw = input().strip()
            if not credentials_raw:
                self.stdout.write("Skipping Google OAuth configuration...")
                return

        try:
            credentials = json.loads(credentials_raw)
        except json.JSONDecodeError as exc:
            msg = "Google OAuth credentials must be valid JSON."
            raise CommandError(msg) from exc

        app_config = credentials.get("web")
        if not isinstance(app_config, dict):
            msg = "Google OAuth credentials must include a 'web' object."
            raise CommandError(msg)

        client_id = app_config.get("client_id")
        client_secret = app_config.get("client_secret")
        if not client_id or not client_secret:
            msg = "Google OAuth credentials must include web.client_id and web.client_secret."
            raise CommandError(msg)

        app = SocialApp.objects.filter(
            provider="google",
            client_id=client_id,
            secret=client_secret,
        ).first()
        if app is None:
            app = SocialApp.objects.create(
                provider="google",
                name=options["name"],
                client_id=client_id,
                secret=client_secret,
                key="",
                provider_id="",
                settings={},
            )
        elif app.name != options["name"]:
            app.name = options["name"]
            app.save(update_fields=["name"])

        existing_app_site_ids = set(app.sites.values_list("id", flat=True))
        missing_sites = [
            site for site in sites if site.id not in existing_app_site_ids
        ]
        if missing_sites:
            app.sites.add(*missing_sites)

        self.stdout.write(self.style.SUCCESS("Successfully configured Google OAuth."))

    def _get_target_sites(self, options):
        site_domains = list(options["site_domains"] or [])
        env_site_domains = os.environ.get("GOOGLE_OAUTH_SITE_DOMAINS", "")
        if env_site_domains:
            site_domains.extend(
                domain.strip() for domain in env_site_domains.split(",") if domain.strip()
            )
        env_site_domain = os.environ.get("GOOGLE_OAUTH_SITE_DOMAIN")
        if env_site_domain:
            site_domains.append(env_site_domain.strip())

        if site_domains:
            sites = list(Site.objects.filter(domain__in=site_domains))
            missing_site_domains = sorted(
                set(site_domains) - {site.domain for site in sites}
            )
            if missing_site_domains:
                msg = (
                    "Could not find site(s) for Google OAuth: "
                    + ", ".join(missing_site_domains)
                )
                raise CommandError(msg)
            return sites

        sites = list(Site.objects.filter(id=1))
        if len(sites) != 1:
            msg = (
                "Default site is missing. Run ensure_default_sites before "
                "ensure_google_oauth."
            )
            raise CommandError(msg)
        return sites
