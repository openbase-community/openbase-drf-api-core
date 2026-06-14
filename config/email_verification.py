from allauth.account.models import EmailAddress


def user_has_verified_email(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return EmailAddress.objects.filter(user=user, verified=True).exists()
