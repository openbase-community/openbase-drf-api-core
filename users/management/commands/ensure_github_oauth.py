from users.oauth_setup import EnsureOAuthSocialAppCommand


class Command(EnsureOAuthSocialAppCommand):
    help = "Ensure a GitHub SocialApp exists for the configured sites."

    provider = "github"
    provider_label = "GitHub"
    env_prefix = "GITHUB_OAUTH"
