"""Tell every account that still signed in with a password that passwords are
retired (see PASSWORD_AUTH_ENABLED in config/settings.py).

Runs once, on the deploy that ships the passwordless release. It changes no
rows: the hashes stay so the switch can be reverted by configuration. It sends
nothing on DEBUG deployments or where PASSWORD_RETIREMENT_NOTICE_SKIP=1, and
nothing while PASSWORD_AUTH_ENABLED=1 keeps passwords working. Preview or
re-send with ``manage.py password_retirement_notice``.
"""

import structlog
from django.conf import settings
from django.db import migrations

logger = structlog.get_logger(__name__)


def send_notices(apps, schema_editor):
    from users.password_retirement import send_password_retirement_notices

    if settings.DEBUG or settings.PASSWORD_RETIREMENT_NOTICE_SKIP:
        logger.info("password_retirement_notice_skipped", reason="debug_or_skip")
        return
    if settings.PASSWORD_AUTH_ENABLED:
        logger.info(
            "password_retirement_notice_skipped", reason="password_auth_enabled"
        )
        return
    send_password_retirement_notices(apps.get_model("users", "User"))


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_alter_user_phone_number_and_more"),
        ("site_attributes", "0004_alter_siteattributes_from_email"),
    ]

    operations = [
        migrations.RunPython(send_notices, migrations.RunPython.noop),
    ]
