from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from appstoreserverlibrary.signed_data_verifier import (
    VerificationException,
    VerificationStatus,
)
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from payment.models import Account, Subscription
from payment.stripe_subscription_events import (
    apply_stripe_subscription_event,
    stripe_subscription_item,
    stripe_subscription_product_id,
)
from payment.views import (
    AppleWebhookView,
    StripeCheckoutView,
    StripeCustomerPortalView,
    StripeWebhookView,
    portal_return_route_label,
)

pytestmark = pytest.mark.django_db


TEST_PRICE_IDS = {
    "pro": "price_pro_test",
    "pro_plus": "price_pro_plus_test",
    "ultra": "price_ultra_test",
}
TEST_SUBSCRIPTION_TIERS = {
    2000: {
        "plan": "pro",
        "name": "Pro",
        "price_setting": "OPENBASE_STRIPE_PRO_PRICE_ID",
        "trial_period_days": 1,
    },
    6000: {
        "plan": "pro_plus",
        "name": "Pro+",
        "price_setting": "OPENBASE_STRIPE_PRO_PLUS_PRICE_ID",
    },
    20000: {
        "plan": "ultra",
        "name": "Ultra",
        "price_setting": "OPENBASE_STRIPE_ULTRA_PRICE_ID",
    },
}


def test_portal_return_route_label_never_retains_path_secrets():
    assert portal_return_route_label("https://app.openbase.cloud/settings/") == "settings"
    assert (
        portal_return_route_label(
            "https://app.openbase.cloud/account/reset/secret-reset-token"
        )
        == "other"
    )


def test_older_stripe_event_cannot_resurrect_terminal_subscription():
    user = get_user_model().objects.create_user(email="ordering@example.com")
    account = Account.objects.get(user_owner=user)
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={"id": "sub_ordering"},
    )
    terminal_object = {
        "id": "sub_ordering",
        "customer": "cus_ordering",
        "status": "canceled",
        "items": {"data": [{"price": {"product": "prod_pro"}}]},
    }
    active_object = {
        **terminal_object,
        "status": "active",
        "current_period_end": int((timezone.now() + timedelta(days=30)).timestamp()),
    }

    terminal_result = apply_stripe_subscription_event(
        account=account,
        event_type="customer.subscription.deleted",
        event_id="evt_new_terminal",
        event_created=200,
        subscription_object=terminal_object,
    )
    stale_result = apply_stripe_subscription_event(
        account=account,
        event_type="customer.subscription.updated",
        event_id="evt_old_active",
        event_created=100,
        subscription_object=active_object,
    )

    subscription.refresh_from_db()
    assert terminal_result == "expired"
    assert stale_result == "ignored_stale"
    assert subscription.expiration_date <= timezone.now()
    assert subscription.stripe_event_id == "evt_new_terminal"
    assert subscription.stripe_event_created == 200
    assert subscription.stripe_event_terminal is True


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_uses_configured_stripe_price_for_default_tier():
    response, session_create = _create_checkout()
    subscription_data = session_create.call_args.kwargs["subscription_data"]

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert session_create.call_args.kwargs["line_items"] == [
        {"price": "price_pro_test", "quantity": 1}
    ]
    assert session_create.call_args.kwargs["allow_promotion_codes"] is True
    assert subscription_data["trial_period_days"] == 1


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_uses_requested_subscription_tier():
    response, session_create = _create_checkout(
        monthly_tier_cents=6000,
    )

    subscription_data = session_create.call_args.kwargs["subscription_data"]

    assert response.status_code == 200
    assert session_create.call_args.kwargs["line_items"] == [
        {"price": "price_pro_plus_test", "quantity": 1}
    ]
    assert subscription_data["metadata"] == {
        "openbase_plan_key": "pro_plus",
        "openbase_plan": "Pro+",
        "openbase_monthly_tier_cents": "6000",
    }
    assert "trial_period_days" not in subscription_data


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_rejects_unknown_subscription_tier():
    response, session_create = _create_checkout(
        monthly_tier_cents=50000,
    )

    assert response.status_code == 400
    assert session_create.call_count == 0


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS={
        "pro": "price_pro_test",
        "pro_plus": "",
        "ultra": "price_ultra_test",
    },
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_rejects_unconfigured_subscription_tier():
    response, session_create = _create_checkout(monthly_tier_cents=6000)

    assert response.status_code == 400
    assert "OPENBASE_STRIPE_PRO_PLUS_PRICE_ID" in str(response.data)
    assert session_create.call_count == 0


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_replaces_missing_stripe_customer_and_retries():
    User = get_user_model()
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_initial"),
    ):
        user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test_mode"
    account.save(update_fields=["customer_id"])
    user.refresh_from_db()

    factory = APIRequestFactory()
    request = factory.post(
        "/api/create-checkout-session/",
        {
            "success_url": "https://app.example.com/success",
            "cancel_url": "https://app.example.com/cancel",
        },
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    missing_customer = stripe.error.InvalidRequestError(
        "No such customer",
        "customer",
    )
    with (
        patch(
            "payment.views.stripe.checkout.Session.create",
            side_effect=[
                missing_customer,
                SimpleNamespace(url="https://checkout.stripe.test/session"),
            ],
        ) as session_create,
        patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_live_mode"),
        ) as customer_create,
    ):
        response = StripeCheckoutView.as_view()(request)

    account.refresh_from_db()

    assert response.status_code == 200
    assert response.data == {"url": "https://checkout.stripe.test/session"}
    assert account.customer_id == "cus_live_mode"
    assert customer_create.call_args.kwargs["email"] == "ada@example.com"
    assert session_create.call_count == 2
    assert session_create.call_args_list[0].kwargs["customer"] == "cus_test_mode"
    assert session_create.call_args_list[1].kwargs["customer"] == "cus_live_mode"


@override_settings(ALLOWED_HOSTS=["app.example.com"])
def test_customer_portal_replaces_test_mode_stripe_customer_and_retries():
    User = get_user_model()
    with patch(
        "users.models.stripe.Customer.create",
        return_value=SimpleNamespace(id="cus_initial"),
    ):
        user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test_mode"
    account.save(update_fields=["customer_id"])
    user.refresh_from_db()

    request = APIRequestFactory().post(
        "/api/customer-portal/",
        {"return_url": "https://app.example.com/dashboard/devspaces"},
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    missing_test_mode_customer = stripe.error.InvalidRequestError(
        "No such customer: 'cus_test_mode'; a similar object exists in test mode, "
        "but a live mode key was used to make this request.",
        None,
    )
    with (
        patch(
            "payment.views.stripe.billing_portal.Session.create",
            side_effect=[
                missing_test_mode_customer,
                SimpleNamespace(url="https://billing.stripe.test/session"),
            ],
        ) as session_create,
        patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_live_mode"),
        ) as customer_create,
    ):
        response = StripeCustomerPortalView.as_view()(request)

    account.refresh_from_db()

    assert response.status_code == 200
    assert response.data == {"url": "https://billing.stripe.test/session"}
    assert account.customer_id == "cus_live_mode"
    assert customer_create.call_args.kwargs["email"] == "ada@example.com"
    assert session_create.call_count == 2
    assert session_create.call_args_list[0].kwargs["customer"] == "cus_test_mode"
    assert session_create.call_args_list[1].kwargs["customer"] == "cus_live_mode"


def test_subscription_deleted_webhook_expires_subscription_and_terminates_resources():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.deleted",
        data=SimpleNamespace(
            object={
                "customer": "cus_live_mode",
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.run_subscription_cancellation_hooks",
            return_value={
                "devspaces_terminated": 1,
                "deployment_teardowns_queued": 2,
            },
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date <= timezone.now()
    terminate_resources.assert_called_once_with(user)


def test_subscription_terminal_status_expires_and_terminates_resources():
    User = get_user_model()
    user = User.objects.create_user(email="terminal-status@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_terminal"
    account.save(update_fields=["customer_id"])
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.updated",
        data=SimpleNamespace(
            object={
                "id": "sub_terminal",
                "customer": "cus_terminal",
                "status": "canceled",
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.run_subscription_cancellation_hooks",
            return_value={"devspaces_terminated": 1},
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date <= timezone.now()
    terminate_resources.assert_called_once_with(user)


def test_subscription_updated_webhook_keeps_scheduled_trial_active():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    cancel_at = int((timezone.now() + timedelta(days=1)).timestamp())
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=1),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.updated",
        data=SimpleNamespace(
            object={
                "id": "sub_trial",
                "customer": "cus_live_mode",
                "status": "trialing",
                "canceled_at": int(timezone.now().timestamp()),
                "cancel_at": cancel_at,
                "cancel_at_period_end": False,
                "trial_end": cancel_at,
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.run_subscription_cancellation_hooks",
            return_value={
                "devspaces_terminated": 1,
                "deployment_teardowns_queued": 2,
            },
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date == datetime.fromtimestamp(cancel_at, tz=UTC)
    assert subscription.platform_data["cancel_at"] == cancel_at
    terminate_resources.assert_not_called()


def test_subscription_updated_webhook_keeps_future_cancel_at_active():
    User = get_user_model()
    user = User.objects.create_user(email="grace@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    cancel_at = int((timezone.now() + timedelta(days=1)).timestamp())
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=1),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.updated",
        data=SimpleNamespace(
            object={
                "id": "sub_trial",
                "customer": "cus_live_mode",
                "status": "trialing",
                "cancel_at": cancel_at,
                "cancel_at_period_end": False,
                "trial_end": cancel_at,
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.run_subscription_cancellation_hooks",
            return_value={
                "devspaces_terminated": 1,
                "deployment_teardowns_queued": 2,
            },
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date == datetime.fromtimestamp(cancel_at, tz=UTC)
    assert subscription.platform_data["cancel_at"] == cancel_at
    terminate_resources.assert_not_called()


def test_subscription_updated_webhook_keeps_cancel_at_period_end_active():
    User = get_user_model()
    user = User.objects.create_user(email="linus@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    period_end = int((timezone.now() + timedelta(days=30)).timestamp())
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={},
    )
    event = SimpleNamespace(
        type="customer.subscription.updated",
        data=SimpleNamespace(
            object={
                "id": "sub_period_end",
                "customer": "cus_live_mode",
                "status": "active",
                "cancel_at_period_end": True,
                "current_period_end": period_end,
                "items": {"data": [{"price": {"product": "prod_pro"}}]},
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch(
            "payment.views.run_subscription_cancellation_hooks",
            return_value={
                "devspaces_terminated": 1,
                "deployment_teardowns_queued": 2,
            },
        ) as terminate_resources,
    ):
        response = StripeWebhookView.as_view()(request)

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.expiration_date == datetime.fromtimestamp(period_end, tz=UTC)
    assert subscription.platform_data["cancel_at_period_end"] is True
    terminate_resources.assert_not_called()


def test_subscription_created_webhook_syncs_item_period_end_for_trials():
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    period_end = int((timezone.now() + timedelta(days=1)).timestamp())
    event = SimpleNamespace(
        type="customer.subscription.created",
        data=SimpleNamespace(
            object={
                "id": "sub_trial",
                "customer": "cus_live_mode",
                "status": "trialing",
                "trial_end": period_end,
                "items": {
                    "data": [
                        {
                            "current_period_end": period_end,
                            "price": {
                                "id": "price_pro_test",
                                "product": "prod_pro",
                            },
                        }
                    ]
                },
            }
        ),
    )
    request = APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )

    with patch("payment.views.stripe.Webhook.construct_event", return_value=event):
        response = StripeWebhookView.as_view()(request)

    subscription = Subscription.objects.get(account=account)
    assert response.status_code == 200
    assert subscription.subscription_type == "prod_pro"
    assert subscription.expiration_date == datetime.fromtimestamp(period_end, UTC)
    assert subscription.platform_data["status"] == "trialing"


def test_stripe_subscription_item_prefers_licensed_item_over_metered_addons():
    subscription_object = {
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_payg",
                        "product": "prod_payg",
                        "recurring": {"interval": "month", "usage_type": "metered"},
                    }
                },
                {
                    "price": {
                        "id": "price_pro_test",
                        "product": "prod_pro",
                        "recurring": {"interval": "month", "usage_type": "licensed"},
                    }
                },
            ]
        }
    }

    item = stripe_subscription_item(subscription_object)

    assert item["price"]["id"] == "price_pro_test"
    assert stripe_subscription_product_id(subscription_object) == "prod_pro"


def test_stripe_subscription_item_falls_back_to_first_item_when_all_metered():
    subscription_object = {
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_payg",
                        "product": "prod_payg",
                        "recurring": {"interval": "month", "usage_type": "metered"},
                    }
                },
            ]
        }
    }

    assert stripe_subscription_product_id(subscription_object) == "prod_payg"


def test_apple_webhook_rejects_unverifiable_payload():
    request = APIRequestFactory().post(
        "/api/apple-webhook/",
        {"signedPayload": "not-a-real-jws"},
        format="json",
    )

    with patch(
        "payment.views.verify_and_decode_notification",
        side_effect=VerificationException(VerificationStatus.VERIFICATION_FAILURE),
    ):
        response = AppleWebhookView.as_view()(request)

    # A 2xx would tell Apple the notification was processed and it would
    # never retry, silently dropping the subscription update.
    assert response.status_code == 400


def _create_checkout(*, monthly_tier_cents=None):
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_test"
    account.save(update_fields=["customer_id"])

    factory = APIRequestFactory()
    payload = {
        "success_url": "https://app.example.com/success",
        "cancel_url": "https://app.example.com/cancel",
    }
    if monthly_tier_cents is not None:
        payload["monthly_tier_cents"] = monthly_tier_cents
    request = factory.post(
        "/api/create-checkout-session/",
        payload,
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    with patch(
        "payment.views.stripe.checkout.Session.create",
        return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
    ) as session_create:
        response = StripeCheckoutView.as_view()(request)

    return response, session_create


def _stripe_subscription(platform_data):
    return Subscription(
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data=platform_data,
    )


def test_stripe_subscription_id_returns_sub_id():
    subscription = _stripe_subscription({"id": "sub_123"})
    assert subscription.stripe_subscription_id == "sub_123"
    assert subscription.is_stripe_billed


@pytest.mark.parametrize(
    "platform_data",
    [
        {},
        {"id": "apple-original-transaction"},
        {"apple": "receipt"},
        None,
        "not-a-dict",
    ],
)
def test_non_stripe_platform_data_is_not_stripe_billed(platform_data):
    subscription = _stripe_subscription(platform_data)
    assert subscription.stripe_subscription_id is None
    assert not subscription.is_stripe_billed


def test_has_price_item_matches_price_id():
    subscription = _stripe_subscription(
        {
            "id": "sub_123",
            "items": {
                "data": [
                    {"price": {"id": "price_flat"}},
                    {"price": {"id": "price_metered"}},
                    "malformed-item",
                    {"price": "malformed-price"},
                ]
            },
        }
    )
    assert subscription.has_price_item("price_metered")
    assert not subscription.has_price_item("price_other")


@pytest.mark.parametrize(
    "platform_data",
    [
        {},
        {"items": "not-a-dict"},
        {"items": {"data": "not-a-list"}},
        {"items": {"data": []}},
    ],
)
def test_stripe_price_items_tolerates_malformed_payloads(platform_data):
    subscription = _stripe_subscription(platform_data)
    assert subscription.stripe_price_items() == []
    assert not subscription.has_price_item("price_flat")
    assert subscription.monthly_licensed_price_cents is None


def test_monthly_licensed_price_cents_uses_flat_monthly_item():
    subscription = _stripe_subscription(
        {
            "items": {
                "data": [
                    {
                        "price": {
                            "unit_amount": 6000,
                            "recurring": {"interval": "month"},
                        }
                    }
                ]
            }
        }
    )
    assert subscription.monthly_licensed_price_cents == 6000


def test_monthly_licensed_price_cents_normalizes_yearly_with_ceiling():
    subscription = _stripe_subscription(
        {
            "items": {
                "data": [
                    {
                        "price": {
                            "unit_amount": 240001,
                            "recurring": {"interval": "year"},
                        }
                    }
                ]
            }
        }
    )
    assert subscription.monthly_licensed_price_cents == 20001


def test_monthly_licensed_price_cents_skips_metered_items():
    subscription = _stripe_subscription(
        {
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_payg",
                            "unit_amount": None,
                            "recurring": {
                                "interval": "month",
                                "usage_type": "metered",
                            },
                        }
                    },
                    {
                        "price": {
                            "unit_amount": 6000,
                            "recurring": {"interval": "month"},
                        }
                    },
                ]
            }
        }
    )
    assert subscription.monthly_licensed_price_cents == 6000


def test_monthly_licensed_price_cents_divides_multi_month_intervals():
    subscription = _stripe_subscription(
        {
            "items": {
                "data": [
                    {
                        "price": {
                            "unit_amount": 6001,
                            "recurring": {"interval": "month", "interval_count": 3},
                        }
                    }
                ]
            }
        }
    )
    assert subscription.monthly_licensed_price_cents == 2001


def test_stripe_customer_id_reads_account():
    User = get_user_model()
    user = User.objects.create_user(email="grace@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_typed"
    account.save(update_fields=["customer_id"])
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + timedelta(days=30),
        platform_data={"id": "sub_typed"},
    )
    assert subscription.stripe_customer_id == "cus_typed"


def test_is_trialing_reads_stripe_status():
    trialing = Subscription(
        subscription_type="prod_pro",
        expiration_date=timezone.now(),
        platform_data={"id": "sub_trial", "status": "trialing"},
    )
    active = Subscription(
        subscription_type="prod_pro",
        expiration_date=timezone.now(),
        platform_data={"id": "sub_live", "status": "active"},
    )
    manual = Subscription(
        subscription_type="manual_lifetime_infinite_cap",
        expiration_date=timezone.now(),
        platform_data=None,
    )
    assert trialing.is_trialing
    assert not active.is_trialing
    assert not manual.is_trialing


def _user_with_subscription(*, expiration_delta, platform_data):
    User = get_user_model()
    user = User.objects.create_user(email="ada@example.com")
    account = Account.objects.get(user_owner=user)
    account.customer_id = "cus_live_mode"
    account.save(update_fields=["customer_id"])
    subscription = Subscription.objects.create(
        account=account,
        subscription_type="prod_pro",
        expiration_date=timezone.now() + expiration_delta,
        platform_data=platform_data,
    )
    return user, account, subscription


def _webhook_request():
    return APIRequestFactory().post(
        "/api/stripe-webhook/",
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="sig_test",
    )


def test_checkout_rejected_while_subscription_is_active():
    user, _account, _subscription = _user_with_subscription(
        expiration_delta=timedelta(days=30),
        platform_data={"id": "sub_current"},
    )
    request = APIRequestFactory().post(
        "/api/create-checkout-session/",
        {},
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    with patch("payment.views.stripe.checkout.Session.create") as session_create:
        response = StripeCheckoutView.as_view()(request)

    assert response.status_code == 400
    assert "billing portal" in response.data["error"]
    session_create.assert_not_called()


@override_settings(
    ALLOWED_HOSTS=["app.example.com"],
    OPENBASE_STRIPE_SUBSCRIPTION_PRICE_IDS=TEST_PRICE_IDS,
    SUBSCRIPTION_TIERS=TEST_SUBSCRIPTION_TIERS,
    DEFAULT_SUBSCRIPTION_TIER_CENTS=2000,
)
def test_checkout_allowed_again_after_subscription_expires():
    user, _account, _subscription = _user_with_subscription(
        expiration_delta=timedelta(days=-1),
        platform_data={"id": "sub_old"},
    )
    request = APIRequestFactory().post(
        "/api/create-checkout-session/",
        {},
        format="json",
        HTTP_HOST="app.example.com",
        secure=True,
    )
    force_authenticate(request, user=user)

    with patch(
        "payment.views.stripe.checkout.Session.create",
        return_value=SimpleNamespace(url="https://checkout.stripe.test/session"),
    ) as session_create:
        response = StripeCheckoutView.as_view()(request)

    assert response.status_code == 200
    session_create.assert_called_once()


def test_webhook_ignores_cancellation_for_untracked_subscription():
    _user, _account, subscription = _user_with_subscription(
        expiration_delta=timedelta(days=30),
        platform_data={"id": "sub_current"},
    )
    event = SimpleNamespace(
        type="customer.subscription.deleted",
        data=SimpleNamespace(
            object={
                "id": "sub_stray",
                "customer": "cus_live_mode",
                "items": {"data": [{"price": {"product": "prod_ultra"}}]},
            }
        ),
    )

    with (
        patch("payment.views.stripe.Webhook.construct_event", return_value=event),
        patch("payment.views.run_subscription_cancellation_hooks") as hooks,
    ):
        response = StripeWebhookView.as_view()(_webhook_request())

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.is_active()
    assert subscription.platform_data == {"id": "sub_current"}
    hooks.assert_not_called()


def test_webhook_ignores_sync_for_untracked_subscription_while_active():
    _user, _account, subscription = _user_with_subscription(
        expiration_delta=timedelta(days=30),
        platform_data={"id": "sub_current"},
    )
    event = SimpleNamespace(
        type="customer.subscription.updated",
        data=SimpleNamespace(
            object={
                "id": "sub_stray",
                "customer": "cus_live_mode",
                "current_period_end": int(
                    (timezone.now() + timedelta(days=7)).timestamp()
                ),
                "items": {"data": [{"price": {"product": "prod_ultra"}}]},
            }
        ),
    )

    with patch("payment.views.stripe.Webhook.construct_event", return_value=event):
        response = StripeWebhookView.as_view()(_webhook_request())

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.platform_data == {"id": "sub_current"}
    assert subscription.subscription_type == "prod_pro"


def test_webhook_adopts_new_subscription_after_previous_expires():
    _user, _account, subscription = _user_with_subscription(
        expiration_delta=timedelta(days=-1),
        platform_data={"id": "sub_old"},
    )
    period_end = int((timezone.now() + timedelta(days=30)).timestamp())
    event = SimpleNamespace(
        type="customer.subscription.created",
        data=SimpleNamespace(
            object={
                "id": "sub_new",
                "customer": "cus_live_mode",
                "current_period_end": period_end,
                "items": {"data": [{"price": {"product": "prod_ultra"}}]},
            }
        ),
    )

    with patch("payment.views.stripe.Webhook.construct_event", return_value=event):
        response = StripeWebhookView.as_view()(_webhook_request())

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.platform_data["id"] == "sub_new"
    assert subscription.subscription_type == "prod_ultra"
    assert subscription.expiration_date == datetime.fromtimestamp(period_end, tz=UTC)
