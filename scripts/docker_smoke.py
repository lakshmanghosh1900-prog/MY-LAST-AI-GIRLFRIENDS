"""Ephemeral container smoke test for a MY LAST AI GIRLFRIENDS image.

Usage:
    uv run --locked python scripts/docker_smoke.py --image <image> [--expect-revision <sha>]

The image is started with no published ports, an isolated network, a dropped
capability set and a tmpfs data directory. The authenticated API is probed from
inside the container and the container is always removed afterwards. The
canonical database and every other local image/container are left untouched.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import time

PROBE_SOURCE = r'''
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
TOKEN = os.environ["MLAG_AUTH_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
CHECKS = {}


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8") or "{}")


def wait_health():
    last = None
    for _ in range(40):
        try:
            status, payload = call("GET", "/v1/health")
            if status == 200:
                return payload
            last = "status %s" % status
        except Exception as exc:  # noqa: BLE001 - container startup race
            last = repr(exc)
        time.sleep(0.5)
    raise SystemExit(json.dumps({"ok": False, "failed": "health", "detail": str(last)}))


health = wait_health()
CHECKS["health_mode"] = health.get("mode")
CHECKS["health_database"] = health.get("database")
CHECKS["health_version"] = health.get("version")
CHECKS["health_ai_fallback_disabled"] = health.get("provider_status", {}).get("ai_generated") in (None, False)

status, readiness = call("GET", "/v1/readiness/local")
CHECKS["readiness_status"] = status
CHECKS["readiness_ready"] = bool(readiness.get("ready_for_local_tests"))
CHECKS["readiness_secret_free"] = bool(readiness.get("secret_free"))

status, created = call("POST", "/v1/conversations", {})
CHECKS["conversation_status"] = status
conversation_id = created.get("id")

status, message = call(
    "POST",
    "/v1/conversations/%s/messages" % conversation_id,
    {"content": "container smoke message"},
)
CHECKS["message_status"] = status
CHECKS["message_result"] = message.get("status")
CHECKS["message_ai_generated"] = message.get("ai_generated")

status, listing = call("GET", "/v1/conversations")
CHECKS["listing_status"] = status
CHECKS["listing_nonempty"] = bool(listing.get("conversations"))

failures = []
if CHECKS["health_database"] != "ready":
    failures.append("health")
if CHECKS["readiness_status"] != 200 or not CHECKS["readiness_ready"]:
    failures.append("readiness")
if CHECKS["conversation_status"] != 201:
    failures.append("conversation")
if CHECKS["message_status"] != 200 or CHECKS["message_result"] != "SUCCEEDED":
    failures.append("message")
if CHECKS["message_ai_generated"] is not False:
    failures.append("offline_truthfulness")
if CHECKS["listing_status"] != 200 or not CHECKS["listing_nonempty"]:
    failures.append("listing")

print(json.dumps({"ok": not failures, "checks": CHECKS, "failures": failures}, sort_keys=True))
sys.exit(1 if failures else 0)
'''


def build_run_command(image: str, name: str, token: str) -> list[str]:
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/app/data:rw,noexec,nosuid,size=128m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "-e",
        f"MLAG_AUTH_TOKEN={token}",
        "-e",
        "MLAG_MODE=offline",
        image,
    ]


def run_command(args: list[str], *, input_bytes: bytes | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout)


def image_revision(image: str) -> str | None:
    result = run_command(
        ["docker", "image", "inspect", "--format", "{{index .Config.Labels \"org.opencontainers.image.revision\"}}", image],
        timeout=60,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.decode("utf-8", "replace").strip()
    return value or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--expect-revision", default=None)
    parser.add_argument("--startup-timeout", type=int, default=30)
    args = parser.parse_args(argv)

    if shutil.which("docker") is None:
        print(json.dumps({"ok": False, "blocked": "DOCKER_UNAVAILABLE"}))
        return 2

    revision = image_revision(args.image)
    if args.expect_revision and revision != args.expect_revision:
        print(
            json.dumps(
                {
                    "ok": False,
                    "failed": "provenance",
                    "expected_revision": args.expect_revision,
                    "image_revision": revision,
                }
            )
        )
        return 1

    token = secrets.token_urlsafe(32)
    name = f"mlag-smoke-{secrets.token_hex(6)}"
    container_id = None
    started = False
    probe_result = None
    try:
        run_result = run_command(build_run_command(args.image, name, token))
        if run_result.returncode != 0:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "failed": "container_start",
                        "detail": run_result.stderr.decode("utf-8", "replace")[-2000:],
                    }
                )
            )
            return 1
        started = True
        container_id = run_result.stdout.decode("utf-8", "replace").strip()
        deadline = time.time() + args.startup_timeout
        probe_result = None
        while time.time() < deadline:
            probe = run_command(["docker", "exec", "-i", name, "python", "-"], input_bytes=PROBE_SOURCE.encode("utf-8"))
            if probe.returncode == 0:
                probe_result = json.loads(probe.stdout.decode("utf-8", "replace"))
                break
            time.sleep(1)
        if probe_result is None:
            logs = run_command(["docker", "logs", name], timeout=60)
            print(
                json.dumps(
                    {
                        "ok": False,
                        "failed": "probe",
                        "detail": (logs.stderr.decode("utf-8", "replace") + logs.stdout.decode("utf-8", "replace"))[-2000:],
                    }
                )
            )
            return 1
        logs = run_command(["docker", "logs", name], timeout=60)
        summary = {
            "ok": bool(probe_result.get("ok")),
            "image": args.image,
            "image_revision": revision,
            "container_id": container_id,
            "checks": probe_result.get("checks"),
            "failures": probe_result.get("failures"),
            "startup_log": logs.stdout.decode("utf-8", "replace").strip().splitlines()[:2],
        }
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["ok"] else 1
    finally:
        if started:
            run_command(["docker", "rm", "-f", name], timeout=120)


if __name__ == "__main__":
    raise SystemExit(main())
