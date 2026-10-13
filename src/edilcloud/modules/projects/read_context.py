"""Opt-in pure reads keep legacy clients compatible during the shared migration."""
from contextlib import contextmanager
from contextvars import ContextVar

_read_only = ContextVar("edilcloud_read_only", default=False)


def read_only_models():
    return _read_only.get()


@contextmanager
def pure_read_models():
    token = _read_only.set(True)
    try:
        yield
    finally:
        _read_only.reset(token)


class ReadModelMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in {"GET", "HEAD"} and request.GET.get("read_only") in {"true", "1"}:
            with pure_read_models():
                return self.get_response(request)
        return self.get_response(request)
