import os

from django.contrib.sites.models import Site
from django.core.management import BaseCommand, CommandError, call_command

from sites.models import SiteAttributes

# Opt-in social providers to (re)provision for a freshly synced deployment
# site. Each command is non-interactive and idempotent: a provider without
# environment credentials is skipped, so this is a no-op unless the deployment
# actually configured that provider.
DEPLOYMENT_OAUTH_PROVIDER_COMMANDS = (
    "ensure_google_oauth",
    "ensure_github_oauth",
    "ensure_apple_oauth",
)


class Command(BaseCommand):
    help = "Create or update a deployment-backed Site and SiteAttributes record."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain", required=True, help="Primary public hostname for the site."
        )
        parser.add_argument(
            "--s3-custom-domain",
            default="",
            help="Optional asset CDN/custom domain used to serve frontend assets.",
        )
        parser.add_argument(
            "--s3-frontend-folder",
            default="",
            help="Optional asset folder inside the configured bucket/CDN.",
        )

    def handle(self, *args, **options):
        domain = str(options["domain"]).strip().lower()
        if not domain:
            msg = "--domain is required."
            raise CommandError(msg)

        defaults = {
            "admin_app_labels": [],
            "s3_frontend_folder": str(options["s3_frontend_folder"]).strip().strip("/"),
            "s3_custom_domain": str(options["s3_custom_domain"]).strip().lower(),
            "stripe_product_id": "prod_implementme",
            "stripe_price_cents": 2000,
            # Prefer an explicitly configured sender (consistent with
            # ensure_default_sites) so a deployment can send from a verified
            # Resend domain instead of team@<domain>, which is often not a
            # verified sending domain (e.g. app.openbase.cloud). Fall back to
            # team@<domain> when DEFAULT_FROM_EMAIL is not set.
            "from_email": os.environ.get("DEFAULT_FROM_EMAIL", "").strip()
            or f"team@{domain}",
        }

        site, _created = Site.objects.update_or_create(
            domain=domain,
            defaults={"name": domain},
        )
        SiteAttributes.objects.update_or_create(site=site, defaults=defaults)
        Site.objects.clear_cache()
        self.stdout.write(self.style.SUCCESS(f"Synced deployment site for {domain}"))

        # A deployment resolves its social providers by request host (in
        # production SITE_ID is None), so each provider's SocialApp must be
        # attached to THIS domain's Site. Now that the Site exists, provision
        # the opt-in providers from their environment credentials so social
        # login works on tenant deployments and not only on the control plane.
        for provider_command in DEPLOYMENT_OAUTH_PROVIDER_COMMANDS:
            call_command(
                provider_command,
                non_interactive=True,
                site_domains=[domain],
            )
