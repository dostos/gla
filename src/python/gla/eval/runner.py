"""Scenario runner: compiles and runs eval GL apps under GLA capture."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from gla.eval.scenario import ScenarioMetadata


class ScenarioRunner:
    """Compiles and runs eval scenarios under GLA capture.

    The runner uses Bazel to build each scenario binary and then launches
    it with LD_PRELOAD pointing at the GLA shim library.
    """

    def __init__(
        self,
        gla_base_url: str = "http://127.0.0.1:18080",
        gla_token: str = "",
        shim_path: str = "",
        bazel_bin: str = "bazel",
        repo_root: Optional[str] = None,
        capture_timeout: float = 5.0,
    ):
        self._base_url = gla_base_url
        self._token = gla_token
        self._shim_path = shim_path
        self._bazel = bazel_bin
        self._capture_timeout = capture_timeout

        if repo_root is not None:
            self._repo_root = Path(repo_root)
        else:
            # Default: walk up from this file to find WORKSPACE / MODULE.bazel
            p = Path(__file__).resolve()
            for parent in p.parents:
                if (parent / "MODULE.bazel").exists() or (parent / "WORKSPACE").exists():
                    self._repo_root = parent
                    break
            else:
                self._repo_root = Path.cwd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_scenario(self, scenario: ScenarioMetadata) -> str:
        """Build the scenario binary via Bazel. Returns absolute binary path."""
        target = f"//tests/eval:{scenario.binary_name}"
        result = subprocess.run(
            [self._bazel, "build", target],
            cwd=str(self._repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Bazel build failed for {target}:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Bazel places binaries at bazel-bin/tests/eval/<name>
        binary = self._repo_root / "bazel-bin" / "tests" / "eval" / scenario.binary_name
        if not binary.exists():
            raise FileNotFoundError(f"Built binary not found at: {binary}")
        return str(binary)

    def run_with_capture(self, scenario: ScenarioMetadata) -> int:
        """Run the scenario binary under GLA capture. Returns the captured frame_id.

        Sets up the environment required by the GLA shim:
          - LD_PRELOAD: path to the GLA interceptor shared library
          - GLA_BASE_URL: HTTP endpoint for the GLA server
          - GLA_TOKEN: bearer token for authentication

        Waits up to self._capture_timeout seconds for frames to appear,
        then queries the GLA server for the latest frame_id.
        """
        binary_path = self.build_scenario(scenario)

        env = os.environ.copy()
        if self._shim_path:
            existing_preload = env.get("LD_PRELOAD", "")
            env["LD_PRELOAD"] = (
                f"{self._shim_path}:{existing_preload}"
                if existing_preload
                else self._shim_path
            )
        env["GLA_BASE_URL"] = self._base_url
        if self._token:
            env["GLA_TOKEN"] = self._token

        proc = subprocess.run(
            [binary_path],
            env=env,
            capture_output=True,
            text=True,
            timeout=self._capture_timeout + 10,
        )
        # Non-zero exit may still have produced frames; don't raise here.

        # Give the server a moment to flush captured data.
        time.sleep(min(self._capture_timeout, 1.0))

        frame_id = self._get_latest_frame_id()
        return frame_id

    def read_source(self, scenario: ScenarioMetadata) -> str:
        """Read and return the scenario C source code."""
        return Path(scenario.source_path).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_latest_frame_id(self) -> int:
        """Query GLA server for the most recent frame_id."""
        import urllib.request
        import json

        url = f"{self._base_url}/api/v1/frames/current/overview"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return int(data.get("frame_id", 0))
        except Exception:
            return 0
