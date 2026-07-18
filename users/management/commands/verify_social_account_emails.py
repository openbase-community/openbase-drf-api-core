from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand

from config.email_verification import (
    ensure_user_email_verified,
    user_has_verified_email,
)


class Command(BaseCommand):
    help = (
        "Mark the primary email verified for users backed by a social provider "
        "account. Heals accounts created before the social-verification "
        "safeguard existed (e.g. Google sign-ins trapped behind the "
        "verified-email gate). Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            help="Only heal the user with this email address.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        target_email = options.get("email")
        dry_run = bool(options["dry_run"])

        user_ids = SocialAccount.objects.values_list("user_id", flat=True).distinct()
        users = User.objects.filter(pk__in=user_ids)
        if target_email:
            normalized = User.objects.normalize_email(target_email).strip().lower()
            users = users.filter(email__iexact=normalized)

        healed = 0
        for user in users:
            if user_has_verified_email(user):
                continue
            self.stdout.write(f"Verifying email for {user.email} (id={user.id}).")
            if not dry_run:
                ensure_user_email_verified(user)
            healed += 1

        verb = "Would verify" if dry_run else "Verified"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {healed} social account user(s).")
        )
