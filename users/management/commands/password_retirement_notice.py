"""Preview or (re)send the password-retirement notice.

The ``users.0003`` migration sends it once per deployment; this command is for
checking who would receive it beforehand (the default, a dry run) and for
sending it again after a failure or on a deployment that skipped the
migration's send.
"""

import json

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand

from users.password_retirement import send_password_retirement_notices


class Command(BaseCommand):
    help = (
        "Mail the password-retirement notice to every active account with a "
        "usable password. Without --send this only reports how many would get it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--send",
            action="store_true",
            help="Actually send the notices (default: dry run, counts only).",
        )

    def handle(self, *args, **options):
        result = send_password_retirement_notices(
            get_user_model(), dry_run=not options["send"]
        )
        self.stdout.write(json.dumps(result.as_dict()))
