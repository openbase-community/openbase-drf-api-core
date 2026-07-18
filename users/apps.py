from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self):
        # Connect the allauth signal receivers that keep social logins verified.
        from users.signals import register_receivers  # noqa: PLC0415

        register_receivers()
