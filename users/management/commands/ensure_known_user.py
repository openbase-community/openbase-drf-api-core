from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = (
        "Create or update a known user, set a deterministic password, and ensure "
        "their email is primary and verified."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email address for the user.")
        parser.add_argument("--password", required=True, help="Password for the user.")
        parser.add_argument(
            "--first-name",
            default="Test",
            help="First name for the user. Default: Test",
        )
        parser.add_argument(
            "--last-name",
            default="User",
            help="Last name for the user. Default: User",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Promote the known user to staff and superuser.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = User.objects.normalize_email(options["email"]).strip().lower()
        password = str(options["password"])
        first_name = str(options["first_name"]).strip()
        last_name = str(options["last_name"]).strip()
        is_superuser = bool(options["superuser"])

        user = User.objects.filter(email=email).first()
        created = user is None
        if user is None:
            user = User.objects.create_user(email=email, password=password)
        else:
            user.set_password(password)

        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.is_staff = is_superuser
        user.is_superuser = is_superuser
        user.save(
            update_fields=[
                "password",
                "first_name",
                "last_name",
                "is_active",
                "is_staff",
                "is_superuser",
            ]
        )

        EmailAddress.objects.filter(user=user).exclude(email=email).update(primary=False)
        email_address, _created = EmailAddress.objects.get_or_create(
            user=user,
            email=email,
            defaults={"verified": True, "primary": True},
        )
        if not email_address.verified or not email_address.primary:
            email_address.verified = True
            email_address.primary = True
            email_address.save(update_fields=["verified", "primary"])

        action = "Created" if created else "Updated"
        role = "superuser" if is_superuser else "user"
        self.stdout.write(self.style.SUCCESS(f"{action} known {role} {email}."))
