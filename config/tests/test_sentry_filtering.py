from config.settings import filter_expected_sentry_events


def test_filter_expected_sentry_events_drops_csrf_cancelled_error():
    event = {
        "exception": {"values": [{"type": "CancelledError"}]},
        "request": {"url": "https://app-staging.openbase.cloud/api/csrf/"},
    }

    assert filter_expected_sentry_events(event, {}) is None


def test_filter_expected_sentry_events_preserves_other_csrf_errors():
    event = {
        "exception": {"values": [{"type": "RuntimeError"}]},
        "request": {"url": "https://app-staging.openbase.cloud/api/csrf/"},
    }

    assert filter_expected_sentry_events(event, {}) == event


def test_filter_expected_sentry_events_preserves_other_cancelled_requests():
    event = {
        "exception": {"values": [{"type": "CancelledError"}]},
        "request": {"url": "https://app-staging.openbase.cloud/api/openbase/"},
    }

    assert filter_expected_sentry_events(event, {}) == event
