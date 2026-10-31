"""Pytest plugin shared by api-core and every app package tested against it.

Registered through ``-p config.pytest_plugin`` in the pytest ``addopts`` so it is
active both for api-core's own suite and for app packages run with
``pytest -c <api-core>/pyproject.toml``.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest
import stripe
from stripe import HTTPClient

_STRIPE_BLOCKED_MESSAGE = (
    "Test attempted a real Stripe API call: {method} {url}. Tests must never reach "
    "Stripe; patch the call site instead (for example "
    '`patch("users.models.stripe.Customer.create")` when a test creates users).'
)


class BlockedStripeHTTPClient(HTTPClient):
    """Stripe HTTP client that fails the test instead of sending a request."""

    name = "blocked-in-tests"

    def __init__(self):
        super().__init__(verify_ssl_certs=True, proxy=None, async_fallback_client=None)

    @staticmethod
    def _blocked(method, url):
        return AssertionError(
            _STRIPE_BLOCKED_MESSAGE.format(method=method.upper(), url=url)
        )

    def request(self, method, url, headers, post_data=None, *args, **kwargs):
        raise self._blocked(method, url)

    def request_stream(self, method, url, headers, post_data=None, *args, **kwargs):
        raise self._blocked(method, url)

    async def request_async(
        self, method, url, headers, post_data=None, *args, **kwargs
    ):
        raise self._blocked(method, url)

    async def request_stream_async(
        self, method, url, headers, post_data=None, *args, **kwargs
    ):
        raise self._blocked(method, url)

    def close(self):
        return None

    async def close_async(self):
        return None


@pytest.fixture(autouse=True)
def block_stripe_network(monkeypatch):
    """Fail any test that reaches the Stripe API instead of patching it.

    `User.get_account()` creates a Stripe customer whenever `STRIPE_SECRET_KEY`
    is set, so an unpatched test that merely creates a user would otherwise
    create a real customer in the configured Stripe account.
    """
    monkeypatch.setattr(stripe, "default_http_client", BlockedStripeHTTPClient())


@pytest.fixture(autouse=True)
def stub_stripe_customer_creation(monkeypatch, block_stripe_network):
    """Give every test a local stand-in for Stripe customer creation.

    `User.save()` calls `get_account()`, which creates a Stripe customer for any
    new account while Stripe is configured, so without this every test that
    creates a user would need its own patch. Tests that care about the customer
    id still patch `users.models.stripe.Customer.create` themselves; nested
    patches win over this stub.
    """
    counter = itertools.count(1)

    def create(**_kwargs):
        return SimpleNamespace(id=f"cus_test_{next(counter)}")

    async def create_async(**kwargs):
        return create(**kwargs)

    monkeypatch.setattr(stripe.Customer, "create", create)
    monkeypatch.setattr(stripe.Customer, "create_async", create_async)
