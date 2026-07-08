import os

from rest_framework.throttling import SimpleRateThrottle


class ContactSubmissionThrottle(SimpleRateThrottle):
    """Per-IP rate limit for the public, unauthenticated contact endpoint.

    Each submission writes a row and sends an email (with an attacker-controlled
    reply-to) via the notification address, so without a throttle the endpoint
    is an inbox-flood / email-cost DoS vector open to the whole internet.
    """

    scope = "contact_submission"

    def get_rate(self) -> str:
        return os.environ.get("CONTACT_SUBMISSION_THROTTLE_RATE", "5/hour")

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
