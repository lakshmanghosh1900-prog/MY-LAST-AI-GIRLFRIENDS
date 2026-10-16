"""CLI entry point for the local service."""

from __future__ import annotations

import os

from .config import ConfigError, load_env_file, Config
from .http_api import JarvisHTTPServer
from .service import JarvisService


def main() -> int:
    load_env_file()
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"configuration safe-stop: {exc}")
        return 2
    service = JarvisService(config)
    server = JarvisHTTPServer((config.host, config.port), service)
    print(f"JARVIS OMEGA listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
