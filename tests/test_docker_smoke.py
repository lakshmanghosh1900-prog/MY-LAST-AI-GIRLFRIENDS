from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "docker_smoke.py"
SPEC = importlib.util.spec_from_file_location("docker_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
DOCKER_SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCKER_SMOKE)


class DockerSmokeTests(unittest.TestCase):
    def test_run_command_is_isolated_and_publishes_no_host_port(self):
        command = DOCKER_SMOKE.build_run_command("example/image:tag", "mlag-smoke-test", "token-value")
        self.assertEqual(command[0], "docker")
        self.assertEqual(command[1:3], ["run", "-d"])
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop", command)
        self.assertIn("--tmpfs", command)
        self.assertNotIn("-p", command)
        self.assertNotIn("--publish", command)
        self.assertNotIn("--privileged", command)
        self.assertEqual(command[-1], "example/image:tag")
        self.assertIn("MLAG_AUTH_TOKEN=token-value", command)

    def test_probe_source_is_valid_python(self):
        compile(DOCKER_SMOKE.PROBE_SOURCE, "probe", "exec")

    def test_missing_docker_is_reported_as_blocked_not_success(self):
        output = io.StringIO()
        with patch.object(DOCKER_SMOKE.shutil, "which", return_value=None):
            with contextlib.redirect_stdout(output):
                result = DOCKER_SMOKE.main(["--image", "example/image:tag"])
        self.assertEqual(result, 2)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["blocked"], "DOCKER_UNAVAILABLE")

    def test_revision_mismatch_fails_before_starting_a_container(self):
        output = io.StringIO()
        with patch.object(DOCKER_SMOKE.shutil, "which", return_value="docker"):
            with patch.object(DOCKER_SMOKE, "image_revision", return_value="other-revision"):
                with patch.object(DOCKER_SMOKE, "run_command") as run:
                    with contextlib.redirect_stdout(output):
                        result = DOCKER_SMOKE.main(["--image", "example/image:tag", "--expect-revision", "expected"])
        self.assertEqual(result, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["failed"], "provenance")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
