from users.oauth_setup import EnsureOAuthSocialAppCommand


class Command(EnsureOAuthSocialAppCommand):
    help = "Ensure a Google SocialApp exists for the configured sites."

    provider = "google"
    provider_label = "Google"
    env_prefix = "GOOGLE_OAUTH"
