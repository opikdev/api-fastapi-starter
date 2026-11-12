"""The image's health check. It imports only the standard library, so it starts in milliseconds."""

import os
import sys
import urllib.request


def main() -> None:
    port = int(os.environ.get("PORT", "3000"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            ok = response.status == 200
    except OSError:
        ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
