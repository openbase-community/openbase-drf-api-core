from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import (
    social_account_added,
    social_account_updated,
)

from config.email_verification import ensure_user_email_verified


def _verify_social_login_email(sociallogin) -> None:
    """Treat any social-provider login as an already-verified email address.

    ``SOCIALACCOUNT_EMAIL_VERIFICATION = "none"`` means allauth never sends a
    confirmation email for social logins, so it also never flips the user's
    ``EmailAddress.verified`` flag on its own. That is fine when the provider
    hands us a ``verified=True`` address, but there are code paths where it does
    not:

    * email-authentication auto-connect, where the social login is attached to a
      pre-existing local account whose ``EmailAddress`` is still unverified, and
    * providers that return an unverified ``email_verified`` claim.

    In those cases the user is left with ``verified=False`` and gets trapped
    behind ``RequireVerifiedEmailMiddleware`` (a 403 ``email_not_verified``)
    with no way to ever receive a verification email. Trusted social providers
    authenticate the email out of band, so we mark it verified here, covering
    every allauth entry point (signup, connect, auto-connect, and repeat login).
    """
    if sociallogin is None:
        return
    ensure_user_email_verified(sociallogin.user)


def _on_user_signed_up(sender, request, user, **kwargs) -> None:
    # Fresh social signups do not emit ``social_account_added`` (that fires only
    # on explicit connect), but they do pass the ``sociallogin`` through here.
    _verify_social_login_email(kwargs.get("sociallogin"))


def _on_social_account_added(sender, request, sociallogin, **kwargs) -> None:
    _verify_social_login_email(sociallogin)


def _on_social_account_updated(sender, request, sociallogin, **kwargs) -> None:
    # Fires on subsequent logins when provider data refreshes; this auto-heals
    # accounts that were created before this safeguard existed.
    _verify_social_login_email(sociallogin)


def register_receivers() -> None:
    user_signed_up.connect(
        _on_user_signed_up, dispatch_uid="users.verify_social_email_on_signup"
    )
    social_account_added.connect(
        _on_social_account_added, dispatch_uid="users.verify_social_email_on_add"
    )
    social_account_updated.connect(
        _on_social_account_updated, dispatch_uid="users.verify_social_email_on_update"
    )
