from config.settings import filter_expected_sentry_events


def _handled_logging_exception(exception_type):
    return {
        "type": exception_type,
        "mechanism": {"type": "logging", "handled": True},
    }


def test_filter_expected_sentry_events_drops_csrf_cancelled_error():
    event = {
        "exception": {"values": [_handled_logging_exception("CancelledError")]},
        "request": {"url": "https://app-staging.openbase.cloud/api/csrf/"},
    }

    assert filter_expected_sentry_events(event, {}) is None


def test_filter_expected_sentry_events_drops_handled_cancelled_request():
    event = {
        "exception": {"values": [_handled_logging_exception("CancelledError")]},
        "request": {
            "url": "https://app-staging.openbase.cloud/_allauth/app/v1/config"
        },
    }

    assert filter_expected_sentry_events(event, {}) is None


def test_filter_expected_sentry_events_preserves_other_csrf_errors():
    event = {
        "exception": {"values": [{"type": "RuntimeError"}]},
        "request": {"url": "https://app-staging.openbase.cloud/api/csrf/"},
    }

    assert filter_expected_sentry_events(event, {}) == event


def test_filter_expected_sentry_events_preserves_unhandled_cancelled_requests():
    event = {
        "exception": {
            "values": [
                {
                    "type": "CancelledError",
                    "mechanism": {"type": "generic", "handled": False},
                }
            ]
        },
        "request": {"url": "https://app-staging.openbase.cloud/api/openbase/"},
    }

    assert filter_expected_sentry_events(event, {}) == event


def test_filter_expected_sentry_events_preserves_mixed_exception_chains():
    event = {
        "exception": {
            "values": [
                _handled_logging_exception("CancelledError"),
                _handled_logging_exception("RuntimeError"),
            ]
        },
        "request": {"url": "https://app-staging.openbase.cloud/api/openbase/"},
    }

    assert filter_expected_sentry_events(event, {}) == event
