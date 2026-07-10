import json

from django.core.management import CommandError

from users.oauth_setup import EnsureOAuthSocialAppCommand, SocialAppCredentials


class Command(EnsureOAuthSocialAppCommand):
    help = "Ensure an Apple SocialApp exists for the configured sites."

    provider = "apple"
    provider_label = "Apple"
    env_prefix = "APPLE_OAUTH"

    def parse_credentials(self, raw):
        """Parse Sign in with Apple credentials.

        Expected JSON object:

        - ``client_id``: the Services ID, optionally followed by additional
          comma-separated audiences (e.g. the iOS app bundle ID for native
          Sign in with Apple). allauth uses the first entry for the web flow
          and accepts any listed audience when verifying native id_tokens.
        - ``key_id``: the Sign in with Apple private key's ID.
        - ``team_id``: the Apple Developer team ID.
        - ``private_key``: the contents of the ``.p8`` private key file.
        """
        try:
            credentials = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = "Apple OAuth credentials must be valid JSON."
            raise CommandError(msg) from exc
        if not isinstance(credentials, dict):
            msg = "Apple OAuth credentials must be a JSON object."
            raise CommandError(msg)

        missing_fields = [
            field
            for field in ("client_id", "key_id", "team_id", "private_key")
            if not credentials.get(field)
        ]
        if missing_fields:
            msg = "Apple OAuth credentials must include " + ", ".join(missing_fields)
            raise CommandError(msg)

        return SocialAppCredentials(
            client_id=credentials["client_id"],
            client_secret=credentials["key_id"],
            key=credentials["team_id"],
            settings={"certificate_key": credentials["private_key"]},
        )
