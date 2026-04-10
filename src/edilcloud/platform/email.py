"""Email delivery helpers shared by transactional modules."""

from concurrent.futures import ThreadPoolExecutor
import logging

from django.conf import settings
from django.db import transaction


LOGGER = logging.getLogger(__name__)
EMAIL_EXECUTOR = ThreadPoolExecutor(
    max_workers=getattr(settings, "EMAIL_THREAD_POOL_SIZE", 2),
    thread_name_prefix="edilcloud-mail",
)


def _send_message_sync(message) -> int:
    return message.send(fail_silently=False)


def _send_message_logged(message) -> None:
    try:
        _send_message_sync(message)
    except Exception:
        LOGGER.exception(
            "Transactional email delivery failed.",
            extra={
                "recipients": list(getattr(message, "to", []) or []),
                "subject": getattr(message, "subject", ""),
            },
        )


def send_email_message(message) -> None:
    """Dispatch an email after commit without blocking the HTTP response in threaded mode."""

    delivery_mode = getattr(settings, "EMAIL_DELIVERY_MODE", "threaded")

    if delivery_mode == "sync":
        _send_message_sync(message)
        return

    def dispatch() -> None:
        EMAIL_EXECUTOR.submit(_send_message_logged, message)

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(dispatch)
        return

    dispatch()
