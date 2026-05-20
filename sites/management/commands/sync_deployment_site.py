from django.contrib.sites.models import Site
from django.core.management import BaseCommand, CommandError

from sites.models import SiteAttributes


class Command(BaseCommand):
    help = "Create or update a deployment-backed Site and SiteAttributes record."

    def add_arguments(self, parser):
        parser.add_argument("--domain", required=True, help="Primary public hostname for the site.")
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
            "from_email": f"team@{domain}",
        }

        site, _created = Site.objects.update_or_create(
            domain=domain,
            defaults={"name": domain},
        )
        SiteAttributes.objects.update_or_create(site=site, defaults=defaults)
        Site.objects.clear_cache()
        self.stdout.write(self.style.SUCCESS(f"Synced deployment site for {domain}"))
