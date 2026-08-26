import pytest

from users.tasks import send_email


class ProviderAuthError(Exception):
    status_code = 401


def test_send_email_does_not_raise_provider_auth_errors(mocker):
    send = mocker.patch("users.tasks.EmailMessage.send", side_effect=ProviderAuthError)
    log_error = mocker.patch("users.tasks.logger.error")

    send_email.original_func("Subject", "<p>Body</p>", "recipient@real-domain.com")

    send.assert_called_once_with()
    log_error.assert_called_once_with(
        "Email provider authentication failed; email task will not retry",
        exception_class="ProviderAuthError",
        status_code=401,
        site_id=None,
        recipients_count=1,
    )


def test_send_email_reraises_non_auth_provider_errors(mocker):
    mocker.patch("users.tasks.EmailMessage.send", side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        send_email.original_func("Subject", "<p>Body</p>", "recipient@real-domain.com")
