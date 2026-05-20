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
            "--non-interactive",
            action="store_true",
            help="Skip prompting and exit successfully when credentials are unavailable.",
        )

    def handle(self, *args, **options):
        if SocialApp.objects.filter(provider="google").exists():
            self.stdout.write("Google OAuth already configured, skipping...")
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

        sites = list(Site.objects.filter(id=1))
        if len(sites) != 1:
            msg = "Default site is missing. Run ensure_default_sites before ensure_google_oauth."
            raise CommandError(msg)

        app = SocialApp.objects.create(
            provider="google",
            name=options["name"],
            client_id=client_id,
            secret=client_secret,
            key="",
            provider_id="",
            settings={},
        )
        app.sites.add(*sites)

        self.stdout.write(self.style.SUCCESS("Successfully configured Google OAuth."))
