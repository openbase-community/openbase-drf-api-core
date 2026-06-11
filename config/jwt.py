import time

from allauth.account.models import EmailAddress
from allauth.core.internal import jwkkit
from allauth.headless import app_settings as headless_app_settings
from allauth.headless.tokens.strategies.jwt import JWTTokenStrategy, internal
from django.conf import settings
from django.http import JsonResponse

# Maps newly issued refresh-token jti -> the jti it superseded.
SUPERSEDES_SESSION_KEY = "headless_refresh_supersedes"


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

    def refresh_token(self, refresh_token: str) -> tuple[str, str] | None:
        """Rotate refresh tokens with acknowledgment instead of immediately.

        Stock allauth (65.13) invalidates the presented refresh token the
        moment a new one is issued. If the refresh response is lost in
        transit (iPhone suspended mid-request, laptop sleeping at the wrong
        moment) or two local processes race to refresh, the client is left
        holding a dead token and the user is forced to log in again.

        Here the presented token stays valid until the token issued from it
        is *used*, which proves the client received it. Old tokens therefore
        survive lost responses and races, while every token still expires at
        its natural ``exp``.
        """
        user_session_payload = internal.validate_refresh_token(refresh_token)
        if user_session_payload is None:
            return None
        user, session, payload = user_session_payload
        access_token = internal.create_access_token(
            user, session, self.get_claims(user)
        )
        if not headless_app_settings.JWT_ROTATE_REFRESH_TOKEN:
            session.save()
            return access_token, refresh_token

        jti = payload["jti"]
        state = internal.get_refresh_token_state(session)
        supersedes: dict[str, str] = session.setdefault(SUPERSEDES_SESSION_KEY, {})

        # Using this token acknowledges its issuance: retire its parent and
        # any sibling tokens whose responses were never received.
        parent_jti = supersedes.pop(jti, None)
        if parent_jti is not None:
            state.pop(parent_jti, None)
            for sibling, sibling_parent in list(supersedes.items()):
                if sibling_parent == parent_jti:
                    supersedes.pop(sibling, None)
                    state.pop(sibling, None)

        jtis_before = set(state)
        next_refresh_token = internal.create_refresh_token(user, session)
        new_jtis = set(state) - jtis_before
        if len(new_jtis) == 1:
            supersedes[set(new_jtis).pop()] = jti

        # Keep session state bounded.
        now = time.time()
        for stale_jti, exp in list(state.items()):
            if exp <= now:
                state.pop(stale_jti, None)
        for issued_jti in list(supersedes):
            if issued_jti not in state:
                supersedes.pop(issued_jti, None)

        session.modified = True
        session.save()
        return access_token, next_refresh_token


def jwks_view(_request):
    jwk_dict, _private_key = jwkkit.load_jwk_from_pem(settings.HEADLESS_JWT_PRIVATE_KEY)
    return JsonResponse({"keys": [jwk_dict]})
