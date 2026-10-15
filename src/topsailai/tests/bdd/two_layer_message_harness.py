"""Owned tmux harness for the two-layer session message BDD suite.

The harness drives the real interactive CLIs (`agent_chats` and
`plan_tasks`) through one uniquely named tmux session per scenario. Startup
and interaction stay in separate shell scripts; this module only orchestrates
them, captures the owned pane, and stops the exact session it created.
"""

from __future__ import annotations

import sys
import subprocess
import time
import uuid
from pathlib import Path

SUPPORT = Path(__file__).resolve().parent / "support"
START_SCRIPT = SUPPORT / "start_two_layer_cli.sh"
INTERACT_SCRIPT = SUPPORT / "interact_two_layer_cli.sh"

PROMPT_MARKER = "Your Turn"
EOF_HINT = "Press 'CTRL D' or Enter 'EOF' for end"


class TwoLayerCLI:
    """Own one isolated tmux session and its captured terminal output."""

    def __init__(self, cli_name: str, endpoint: str, run_dir: Path) -> None:
        """Create a uniquely named session descriptor for one CLI."""
        self.cli_name = cli_name
        self.session = f"bdd-cli-{uuid.uuid4().hex[:10]}"
        self.endpoint = endpoint
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def start(self, timeout: float = 60) -> str:
        """Start the separate CLI startup script in tmux and wait for readiness."""
        subprocess.run(
            [
                "tmux", "new-session", "-d", "-s", self.session,
                "-x", "240", "-y", "80",
                str(START_SCRIPT), self.cli_name, self.endpoint, str(self.run_dir),
                str(Path(sys.executable).parent),
            ],
            check=True,
        )
        return self.wait_for(PROMPT_MARKER, timeout)

    def send(
        self,
        command: str,
        *,
        multiline: bool = False,
        expected: str | None = None,
        timeout: float = 60,
    ) -> str:
        """Send one business or slash command through the interaction script."""
        mode = "multiline" if multiline else "single"
        baseline = self.capture()
        subprocess.run(
            [str(INTERACT_SCRIPT), str(self.run_dir), mode, command],
            check=True,
        )
        if expected is not None:
            self.wait_for_new(expected, baseline.count(expected), timeout)
        return self.wait_for_new(PROMPT_MARKER, baseline.count(PROMPT_MARKER), timeout)

    def capture(self) -> str:
        """Capture the owned pane output."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", self.session, "-S", "-4000"],
            check=True, capture_output=True, text=True,
        )
        return "\n".join(line.rstrip() for line in result.stdout.splitlines())

    def wait_for_new(self, text: str, previous_count: int, timeout: float) -> str:
        """Wait until a newly produced occurrence appears in the owned pane."""
        deadline = time.monotonic() + timeout
        latest = ""
        while time.monotonic() < deadline:
            latest = self.capture()
            if latest.count(text) > previous_count:
                return latest
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for new {text!r}; pane was:\n{latest}")

    def wait_for(self, text: str, timeout: float) -> str:
        """Poll the owned pane until text appears or fail with its output."""
        deadline = time.monotonic() + timeout
        latest = ""
        while time.monotonic() < deadline:
            latest = self.capture()
            if text in latest:
                return latest
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for {text!r}; pane was:\n{latest}")

    def stop(self) -> None:
        """Stop only this test's tmux session and persist its final pane."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-J", "-t", self.session, "-S", "-4000"],
                capture_output=True, text=True, check=False,
            )
            (self.run_dir / "terminal.log").write_text(result.stdout, encoding="utf-8")
        finally:
            subprocess.run(["tmux", "kill-session", "-t", self.session], check=False)
