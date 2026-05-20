import os

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Create a development superuser if needed and ensure its profile defaults are set."

    def add_arguments(self, parser):
        parser.add_argument(
            "--non-interactive",
            action="store_true",
            help="Create or update the development superuser without prompting.",
        )
        parser.add_argument(
            "--email",
            help="Email address to use for non-interactive superuser creation.",
        )
        parser.add_argument(
            "--password",
            help="Password to use for non-interactive superuser creation.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        superuser = User.objects.filter(is_superuser=True).first()

        if superuser is None:
            if options["non_interactive"]:
                superuser = self._create_non_interactive_superuser(
                    User=User,
                    email=options.get("email"),
                    password=options.get("password"),
                )
            else:
                self.stdout.write(
                    "No superuser found. Creating superuser (press CTRL+C to skip)..."
                )
                try:
                    call_command("createsuperuser")
                except KeyboardInterrupt:
                    self.stdout.write("Skipping superuser creation.")
                    return
                superuser = User.objects.filter(is_superuser=True).first()
                if superuser is None:
                    self.stdout.write("No superuser was created.")
                    return
        else:
            self.stdout.write("Superuser already exists, skipping creation...")

        superuser.first_name = "Test"
        superuser.last_name = "User"
        superuser.save()

        email_address, _created = EmailAddress.objects.get_or_create(
            user=superuser,
            email=superuser.email,
            defaults={"verified": True, "primary": True},
        )
        if not email_address.verified or not email_address.primary:
            email_address.verified = True
            email_address.primary = True
            email_address.save(update_fields=["verified", "primary"])

        self.stdout.write(
            self.style.SUCCESS(f"Prepared development superuser {superuser.email}.")
        )

    def _create_non_interactive_superuser(self, *, User, email, password):
        email = email or os.environ.get("DEV_SUPERUSER_EMAIL", "test@example.com")
        password = password or os.environ.get("DEV_SUPERUSER_PASSWORD", "test")

        superuser = User.objects.filter(email=email).first()
        if superuser is None:
            self.stdout.write(
                f"No superuser found. Creating development superuser {email} non-interactively..."
            )
            return User.objects.create_superuser(email=email, password=password)

        self.stdout.write(
            f"No superuser found. Promoting existing user {email} non-interactively..."
        )
        superuser.is_staff = True
        superuser.is_superuser = True
        superuser.is_active = True
        superuser.set_password(password)
        superuser.save(update_fields=["is_staff", "is_superuser", "is_active", "password"])
        return superuser
