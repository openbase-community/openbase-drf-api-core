from allauth.account.models import EmailAddress


def user_has_verified_email(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return EmailAddress.objects.filter(user=user, verified=True).exists()


def ensure_user_email_verified(user) -> None:
    if not user or not user.is_authenticated:
        return
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return
    email_address, _created = EmailAddress.objects.update_or_create(
        user=user,
        email=email,
        defaults={
            "verified": True,
            "primary": True,
        },
    )
    EmailAddress.objects.filter(user=user, primary=True).exclude(
        pk=email_address.pk
    ).update(primary=False)
