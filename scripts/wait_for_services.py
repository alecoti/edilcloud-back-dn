from __future__ import annotations

import socket
import sys
import time


def parse_target(raw: str) -> tuple[str, int]:
    host, separator, port = raw.partition(":")
    if not host or not separator or not port:
      raise ValueError(f"Invalid target '{raw}'. Use host:port.")
    return host, int(port)


def wait_for_target(host: str, port: int, timeout_seconds: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"[wait-for-services] {host}:{port} ready", flush=True)
                return
        except OSError as error:
            last_error = error
            print(f"[wait-for-services] waiting for {host}:{port} ({error})", flush=True)
            time.sleep(2)

    raise TimeoutError(f"Timed out waiting for {host}:{port}: {last_error}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python scripts/wait_for_services.py host:port [host:port...]", file=sys.stderr)
        return 1

    for raw_target in argv[1:]:
        host, port = parse_target(raw_target)
        wait_for_target(host, port)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
