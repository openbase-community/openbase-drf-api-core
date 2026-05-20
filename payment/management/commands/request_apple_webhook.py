from appstoreserverlibrary.api_client import AppStoreServerAPIClient
from appstoreserverlibrary.models.Environment import Environment
from django.conf import settings
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Request Apple webhook for debugging"

    def handle(self, *args, **options):
        key_id = settings.APPLE_STOREKIT_KEY_ID
        issuer_id = settings.APPLE_STOREKIT_ISSUER_ID
        bundle_id = settings.APPLE_BUNDLE_ID
        environment = Environment.PRODUCTION

        client = AppStoreServerAPIClient(
            settings.APPLE_STOREKIT_P8_CONTENTS.encode(),
            key_id,
            issuer_id,
            bundle_id,
            environment,
        )

        response = client.request_test_notification()
        self.stdout.write(str(response))
