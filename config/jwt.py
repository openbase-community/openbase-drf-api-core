from allauth.account.models import EmailAddress
from allauth.core.internal import jwkkit
from allauth.headless.tokens.strategies.jwt import JWTTokenStrategy
from django.conf import settings
from django.http import JsonResponse


class OpenbaseJWTTokenStrategy(JWTTokenStrategy):
    def get_claims(self, user) -> dict[str, str]:
        claims = super().get_claims(user)
        claims["iss"] = settings.HEADLESS_JWT_ISSUER
        claims["aud"] = settings.HEADLESS_JWT_AUDIENCE

        email = (getattr(user, "email", "") or "").strip()
        if not email:
            email_address = (
                EmailAddress.objects.filter(user=user)
                .order_by("-primary", "-verified", "pk")
                .values_list("email", flat=True)
                .first()
            )
            email = (email_address or "").strip()

        if email:
            claims["email"] = email

        return claims


def jwks_view(_request):
    jwk_dict, _private_key = jwkkit.load_jwk_from_pem(settings.HEADLESS_JWT_PRIVATE_KEY)
    return JsonResponse({"keys": [jwk_dict]})
