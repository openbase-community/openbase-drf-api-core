from types import SimpleNamespace

from django.core.mail import EmailMessage

from config.email import (
    ResendEmailBackend,
    format_from_email,
    get_effective_site_from_email,
    is_filtered_email_address,
)


def test_filter_recognizes_dummy_recipients_case_insensitively():
    assert is_filtered_email_address("test@real-domain.com")
    assert is_filtered_email_address("Test User <TEST@real-domain.com>")
    assert is_filtered_email_address("person@EXAMPLE.COM")
    assert is_filtered_email_address("person@subdomain.example.org")
    assert is_filtered_email_address("openbase-field-test@accounts.openbase.test")
    assert is_filtered_email_address("openbase-field-test@accounts.openbase.invalid")


def test_filter_allows_addresses_outside_hard_coded_rules():
    assert not is_filtered_email_address("testing@real-domain.com")
    assert not is_filtered_email_address("person@example.co")
    assert not is_filtered_email_address("person@real-domain.com")
    assert not is_filtered_email_address(
        "delivered+openbase-field-run-a7f3@resend.dev"
    )


def test_backend_does_not_send_messages_with_only_filtered_recipients(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("RESEND_API_KEY", "unused-test-key")
    send = mocker.patch("config.email.resend.Emails.send")
    email_message = EmailMessage(
        subject="Filtered recipients",
        body="This message must not be sent.",
        from_email="sender@real-domain.com",
        to=["test@real-domain.com", "person@example.com"],
    )

    sent_count = ResendEmailBackend().send_messages([email_message])

    assert sent_count == 0
    send.assert_not_called()


def test_backend_does_not_call_resend_for_reserved_field_test_domains(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("RESEND_API_KEY", "unused-test-key")
    send = mocker.patch("config.email.resend.Emails.send")
    email_message = EmailMessage(
        subject="Field-test verification",
        body="This message must never reach the provider.",
        from_email="sender@real-domain.com",
        to=[
            "openbase-field-test-run-1@example.com",
            "openbase-field-test-run-2@accounts.openbase.test",
            "openbase-field-test-run-3@accounts.openbase.invalid",
        ],
    )

    sent_count = ResendEmailBackend().send_messages([email_message])

    assert sent_count == 0
    send.assert_not_called()


def test_backend_submits_official_resend_field_test_recipient(monkeypatch, mocker):
    monkeypatch.setenv("RESEND_API_KEY", "unused-test-key")
    send = mocker.patch("config.email.resend.Emails.send")
    recipient = "delivered+openbase-field-run-a7f3@resend.dev"
    email_message = EmailMessage(
        subject="Field-test verification",
        body="Follow the normal verification flow.",
        from_email="sender@real-domain.com",
        to=[recipient],
    )

    sent_count = ResendEmailBackend().send_messages([email_message])

    assert sent_count == 1
    assert send.call_args.args[0]["to"] == [recipient]


def test_format_from_email_wraps_plain_address_with_site_name():
    assert (
        format_from_email("Openbase Cloud", "team@openbase.cloud")
        == "Openbase Cloud <team@openbase.cloud>"
    )


def test_format_from_email_preserves_configured_display_name():
    assert (
        format_from_email("App Staging", "Openbase Cloud <team@openbase.cloud>")
        == "Openbase Cloud <team@openbase.cloud>"
    )


def test_format_from_email_rejects_malformed_sender():
    try:
        format_from_email("Openbase Cloud", "Openbase Cloud <not-an-address>")
    except ValueError as exc:
        assert str(exc) == "From email address is invalid."
    else:
        raise AssertionError("Malformed sender should raise ValueError.")


def test_site_from_email_prefers_default_for_generated_sender(monkeypatch):
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "team@openbase.cloud")
    site = SimpleNamespace(domain="app-staging.openbase.cloud", name="Staging")
    site_attributes = SimpleNamespace(
        from_email="team@app-staging.openbase.cloud",
    )

    assert get_effective_site_from_email(site, site_attributes) == "team@openbase.cloud"


def test_site_from_email_preserves_formatted_default_sender(monkeypatch):
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "Openbase Cloud <team@openbase.cloud>")
    site = SimpleNamespace(domain="app-staging.openbase.cloud", name="Staging")
    site_attributes = SimpleNamespace(
        from_email="team@app-staging.openbase.cloud",
    )

    sender = format_from_email(
        site.name,
        get_effective_site_from_email(site, site_attributes),
    )

    assert sender == "Openbase Cloud <team@openbase.cloud>"


def test_site_from_email_keeps_custom_sender(monkeypatch):
    monkeypatch.setenv("DEFAULT_FROM_EMAIL", "team@openbase.cloud")
    site = SimpleNamespace(domain="tenant.example.com", name="Tenant")
    site_attributes = SimpleNamespace(from_email="support@example.com")

    assert get_effective_site_from_email(site, site_attributes) == "support@example.com"


def test_backend_removes_filtered_addresses_from_every_recipient_field(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("RESEND_API_KEY", "unused-test-key")
    send = mocker.patch("config.email.resend.Emails.send")
    email_message = EmailMessage(
        subject="Mixed recipients",
        body="Only real recipients should receive this.",
        from_email="sender@real-domain.com",
        to=["real-to@real-domain.com", "test@real-domain.com"],
        cc=["real-cc@real-domain.com", "person@example.net"],
        bcc=["real-bcc@real-domain.com", "person@example.org"],
    )

    sent_count = ResendEmailBackend().send_messages([email_message])

    assert sent_count == 1
    send_params = send.call_args.args[0]
    assert send_params["to"] == ["real-to@real-domain.com"]
    assert send_params["cc"] == ["real-cc@real-domain.com"]
    assert send_params["bcc"] == ["real-bcc@real-domain.com"]
