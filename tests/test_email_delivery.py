from unittest.mock import Mock

from django.test import override_settings

from edilcloud.platform import email as email_platform


class DummyMessage:
    def __init__(self):
        self.sent = 0
        self.to = ["test@example.com"]
        self.subject = "Dummy"

    def send(self, fail_silently=False):
        self.sent += 1
        return 1


@override_settings(EMAIL_DELIVERY_MODE="sync")
def test_send_email_message_sends_immediately_in_sync_mode():
    message = DummyMessage()

    email_platform.send_email_message(message)

    assert message.sent == 1


@override_settings(EMAIL_DELIVERY_MODE="threaded")
def test_send_email_message_uses_executor_in_threaded_mode(monkeypatch):
    message = DummyMessage()
    submit = Mock()
    monkeypatch.setattr(email_platform.EMAIL_EXECUTOR, "submit", submit)

    email_platform.send_email_message(message)

    submit.assert_called_once()
    submitted_callable = submit.call_args.args[0]
    submitted_message = submit.call_args.args[1]
    assert submitted_callable is email_platform._send_message_logged
    assert submitted_message is message


@override_settings(EMAIL_DELIVERY_MODE="threaded")
def test_send_email_message_registers_on_commit_inside_atomic_block(monkeypatch):
    message = DummyMessage()
    submit = Mock()
    registered_callbacks: list = []

    class DummyConnection:
        in_atomic_block = True

    monkeypatch.setattr(email_platform.EMAIL_EXECUTOR, "submit", submit)
    monkeypatch.setattr(email_platform.transaction, "get_connection", lambda: DummyConnection())
    monkeypatch.setattr(
        email_platform.transaction,
        "on_commit",
        lambda callback: registered_callbacks.append(callback),
    )

    email_platform.send_email_message(message)

    assert submit.call_count == 0
    assert len(registered_callbacks) == 1

    registered_callbacks[0]()

    submit.assert_called_once_with(email_platform._send_message_logged, message)
