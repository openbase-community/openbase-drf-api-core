import time

from allauth.account.models import EmailAddress
from allauth.core.internal import jwkkit
from allauth.headless import app_settings as headless_app_settings
from allauth.headless.tokens.strategies.jwt import JWTTokenStrategy, internal
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import JsonResponse

from config.jwt_analytics import notify_jwt_issued

# Maps newly issued refresh-token jti -> the jti it superseded.
SUPERSEDES_SESSION_KEY = "headless_refresh_supersedes"


class ApiCoreJWTTokenStrategy(JWTTokenStrategy):
    def create_session_token(self, request) -> str:
        """Expose auth-flow sessions before mandatory email verification.

        django-allauth 65.13's JWT strategy asserts that ``request.user`` is
        authenticated before returning the session token. A mandatory email
        verification signup is intentionally unauthenticated at this point,
        but the app client still needs the session token to continue the
        verification flow. Newer allauth releases removed that assertion; keep
        the compatible behavior here while deployments remain on 65.13.
        """
        if not request.session.session_key:
            request.session.save()
        key = request.session.session_key
        if not isinstance(key, str):
            msg = "Django did not create a session key."
            raise TypeError(msg)
        return key

    def create_access_token_payload(self, request) -> dict | None:
        payload = super().create_access_token_payload(request)
        if payload is not None:
            notify_jwt_issued(
                user=request.user,
                session=request.session,
                request=request,
                source="headless_token_payload",
            )
        return payload

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
            notify_jwt_issued(
                user=user,
                session=session,
                source="refresh_token",
            )
            return access_token, refresh_token

        jti = payload["jti"]
        with transaction.atomic():
            # Sessions are whole-blob last-write-wins: two concurrent
            # refreshes both read the same state, and the loser's save erases
            # the winner's freshly issued child jti, logging that client out
            # on its next use. Serialize the read-modify-write by locking the
            # session row and re-reading the freshest state.
            session = self._locked_rotation_session(session, payload)
            if session is None:
                # A concurrent request retired this token after we validated
                # it; serialized execution would reject it too.
                return None

            state = internal.get_refresh_token_state(session)
            supersedes: dict[str, str] = session.setdefault(SUPERSEDES_SESSION_KEY, {})

            # Using this token acknowledges its issuance: retire its parent
            # and any sibling tokens whose responses were never received.
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
        notify_jwt_issued(
            user=user,
            session=session,
            source="refresh_token",
        )
        return access_token, next_refresh_token

    @staticmethod
    def _locked_rotation_session(session, payload):
        """Lock the session row and return the freshest session to mutate.

        Must run inside a transaction. Takes ``SELECT ... FOR UPDATE`` on the
        DB session row so concurrent rotations for the same session are
        serialized, then re-loads the session (a competing request may have
        committed between token validation and lock acquisition). Returns the
        reloaded session, the original session when there is no DB row to
        lock (session never persisted, or a non-DB session engine), or
        ``None`` when the presented token was retired concurrently.
        """
        locked_row = (
            Session.objects.select_for_update()
            .filter(session_key=session.session_key)
            .first()
        )
        if locked_row is None:
            return session
        reloaded_session = internal.get_token_session(payload)
        if reloaded_session is None:
            return session
        exp = internal.get_refresh_token_state(reloaded_session).get(payload["jti"])
        if exp is None or exp <= time.time():
            return None
        return reloaded_session


OpenbaseJWTTokenStrategy = ApiCoreJWTTokenStrategy


def jwks_view(_request):
    jwk_dict, _private_key = jwkkit.load_jwk_from_pem(settings.HEADLESS_JWT_PRIVATE_KEY)
    return JsonResponse({"keys": [jwk_dict]})
