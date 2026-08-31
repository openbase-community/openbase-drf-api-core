from django.core.mail import EmailMessage

from config.email import ResendEmailBackend, is_filtered_email_address


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
