import os
from uuid import uuid4

from django.contrib.sites.models import Site
from django.core.management import BaseCommand
from django.db import transaction

from sites.models import SiteAttributes


class Command(BaseCommand):
    help = "Ensure the default local development sites and their site attributes exist."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            dest="domains",
            action="append",
            default=[],
            help="Additional hostname to ensure in the Site table. Repeat for multiple domains.",
        )
        parser.add_argument(
            "--from-allowed-hosts",
            action="store_true",
            help="Also ensure every hostname listed in ALLOWED_HOSTS.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        site_definitions = ((1, {"name": "localhost", "domain": "localhost"}),)
        site_attribute_defaults = {
            "admin_app_labels": [],
            "s3_frontend_folder": "only-used-in-production",
            "stripe_product_id": "prod_implementme",
            "stripe_price_cents": 2000,
            "from_email": "team@my-app.openbase.app",
        }

        for site_id, site_defaults in site_definitions:
            site = self._ensure_site(site_id=site_id, site_defaults=site_defaults)
            SiteAttributes.objects.get_or_create(
                site=site, defaults=site_attribute_defaults
            )

        for domain in self._extra_domains(options):
            site, _created = Site.objects.update_or_create(
                domain=domain,
                defaults={"name": domain},
            )
            SiteAttributes.objects.get_or_create(site=site, defaults=site_attribute_defaults)

        Site.objects.clear_cache()
        self.stdout.write(
            self.style.SUCCESS("Ensured default development sites and attributes.")
        )

    def _ensure_site(self, *, site_id, site_defaults):
        site = Site.objects.select_for_update().filter(id=site_id).first()
        conflicting_site = (
            Site.objects.select_for_update()
            .filter(domain=site_defaults["domain"])
            .exclude(id=site_id)
            .first()
        )

        if site is None:
            if conflicting_site is None:
                return Site.objects.create(id=site_id, **site_defaults)

            site = Site.objects.create(
                id=site_id,
                name=site_defaults["name"],
                domain=self._temporary_domain(site_id),
            )

        if conflicting_site is not None:
            self._move_related_records(source_site=conflicting_site, target_site=site)
            conflicting_site.delete()

        for field_name, value in site_defaults.items():
            setattr(site, field_name, value)
        site.save(update_fields=list(site_defaults))
        return site

    def _move_related_records(self, *, source_site, target_site):
        for relation in Site._meta.related_objects:
            field_name = relation.field.name
            related_manager = relation.related_model._default_manager

            if relation.one_to_one:
                related_object = related_manager.filter(**{field_name: source_site}).first()
                if related_object is None:
                    continue

                target_exists = related_manager.filter(**{field_name: target_site}).exists()
                if target_exists:
                    related_object.delete()
                    continue

                setattr(related_object, field_name, target_site)
                related_object.save(update_fields=[field_name])
                continue

            if relation.one_to_many:
                related_manager.filter(**{field_name: source_site}).update(
                    **{field_name: target_site}
                )
                continue

            if relation.many_to_many:
                through_model = relation.through
                source_field_name = relation.field.m2m_reverse_field_name()
                target_field_name = relation.field.m2m_field_name()

                for related_link in through_model._default_manager.filter(
                    **{source_field_name: source_site}
                ):
                    through_model._default_manager.get_or_create(
                        **{
                            source_field_name: target_site,
                            target_field_name: getattr(related_link, target_field_name),
                        }
                    )

                through_model._default_manager.filter(
                    **{source_field_name: source_site}
                ).delete()

    def _temporary_domain(self, site_id):
        return f"default-site-{site_id}-{uuid4().hex}.invalid"[:100]

    def _extra_domains(self, options):
        domains = {domain.strip().lower() for domain in options["domains"] if domain.strip()}
        if options["from_allowed_hosts"]:
            domains.update(
                host.strip().lower()
                for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
                if host.strip()
            )
        domains.discard("localhost")
        return sorted(domains)
