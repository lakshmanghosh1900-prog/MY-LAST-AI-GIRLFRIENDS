"""CLI entry point for MY LAST AI GIRLFRIENDS."""

from __future__ import annotations

import argparse
import datetime
import sqlite3
from pathlib import Path
import sys

from .config import Config, ConfigError, diagnose_environment, generate_auth_token, load_environment
from .http_api import MyLastAIGirlfriendsHTTPServer
from .service import MyLastAIGirlfriendsService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="my-last-ai-girlfriends")
    parser.add_argument("command", nargs="?", choices={"serve", "doctor", "generate-token"}, default="serve")
    args = parser.parse_args(argv)
    report = load_environment()
    if args.command == "doctor":
        print(diagnose_environment(report))
        return 0
    if args.command == "generate-token":
        token = generate_auth_token()
        env_path = Path(".env")
        if env_path.exists():
            source = env_path.read_text(encoding="utf-8")
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            env_path.replace(Path(f".env.before-token-rotation.{stamp}"))
        else:
            source = Path(".env.example").read_text(encoding="utf-8") if Path(".env.example").exists() else ""
        lines = source.splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith("MLAG_AUTH_TOKEN="):
                lines[index] = f"MLAG_AUTH_TOKEN={token}"
                replaced = True
        if not replaced:
            lines.insert(0, f"MLAG_AUTH_TOKEN={token}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Never print the token. The owner can enter the value from the ignored
        # local .env using their own secure local workflow.
        print("Generated a fresh local authentication token and saved it to the ignored .env file.")
        return 0
    try:
        config = Config.from_report(report)
    except ConfigError as exc:
        print(f"configuration safe-stop: {exc}", file=sys.stderr)
        return 2
    try:
        service = MyLastAIGirlfriendsService(config)
        server = MyLastAIGirlfriendsHTTPServer((config.host, config.port), service)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"startup safe-stop: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"MY LAST AI GIRLFRIENDS listening on http://{config.host}:{config.port} ({config.mode} mode)")
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
