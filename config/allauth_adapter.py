from dataclasses import dataclass
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_display
from allauth.core import context
from allauth.headless.adapter import DefaultHeadlessAdapter
from django.conf import settings

from config.email import get_request_from_email
from config.email_verification import user_has_verified_email


class AccountAdapter(DefaultAccountAdapter):
    def get_from_email(self) -> str:
        return get_request_from_email(context.request)

    def authenticate(self, request, **credentials):
        """Refuse every password login while password authentication is retired.

        allauth's headless ``/auth/login`` and its classic login form both come
        through here, so this one check closes them without touching the
        authentication backends (whose paths live inside every existing
        session). Login-by-code and social logins identify the user themselves
        and never call this method. The stored hashes are left alone.
        """
        if "password" in credentials and not settings.PASSWORD_AUTH_ENABLED:
            return None
        return super().authenticate(request, **credentials)


@dataclass
class UserDataclass:
    id: int
    email: str
    first_name: str
    last_name: str
    display: str
    email_verified: bool


class HeadlessAdapter(DefaultHeadlessAdapter):
    def get_user_dataclass(self):
        return UserDataclass

    def user_as_dataclass(self, user):
        return UserDataclass(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            display=user_display(user),
            email_verified=user_has_verified_email(user),
        )

    def serialize_user(self, user) -> dict[str, Any]:
        """
        From allauth docs: Do not override this method if you would like your customized user payloads
        to be reflected in the (dynamically rendered) OpenAPI specification. In that
        case, override ``get_user_dataclass()`` and ``user_as_dataclass`` instead.
        """
        return {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display": user_display(user),
            "has_usable_password": user.has_usable_password(),
            "email_verified": user_has_verified_email(user),
        }
