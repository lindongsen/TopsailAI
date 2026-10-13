"""Real script subprocess verification. Author: DawsonLin."""

import json
import os
from pathlib import Path
import time

import pytest

from topsailai.scripts import start_script


def _script(tmp_path, content):
    """Create a task-local executable Python child."""
    path = tmp_path / "child.py"
    path.write_text(content)
    path.chmod(0o755)
    return path


def test_real_arguments(tmp_path):
    """Prove literal argv boundaries through a real child process."""
    output = tmp_path / "argv.json"
    path = _script(tmp_path, "import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n")
    arguments = ["space value", "中文", "$(echo no);*", ""]
    with start_script(path, [str(output), *arguments], cwd=tmp_path) as child:
        assert child.wait(timeout=10) == 0
    assert json.loads(output.read_text()) == arguments
    assert child.returncode == 0


def test_real_child_reaping(tmp_path):
    """Leaving the context must stop and reap the exact long-lived child."""
    path = _script(tmp_path, "import time\ntime.sleep(60)\n")
    with start_script(path, shutdown_timeout=0.2) as child:
        assert child.poll() is None
    assert child.returncode is not None
    assert child.wait(timeout=1) == child.returncode


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal resistance fixture")
def test_real_kill_escalation(tmp_path):
    """Force-kill a ready child that explicitly ignores graceful termination."""
    ready = tmp_path / "ready"
    path = _script(tmp_path, "import signal,time,sys\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nPath(sys.argv[1]).touch()\ntime.sleep(60)\n")
    with start_script(path, [str(ready)], shutdown_timeout=0.1) as child:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
    assert child.returncode == -9


def test_driver_help(tmp_path, capfd):
    """Launch the real driver help without sessions or external model calls."""
    home = tmp_path / "home"
    home.mkdir()
    overrides = {
        "TOPSAILAI_HOME": str(home), "TOPSAILAI_EVENTS_ENABLED": "0",
        "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0",
        "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(tmp_path),
    }
    with start_script("session_agent_driver/session_agent_driver.py", ["--help"],
                      cwd=tmp_path, env=overrides) as child:
        assert child.wait(timeout=30) == 0
    output = capfd.readouterr().out
    for option in ("--session", "--poll-interval", "--timeout"):
        assert option in output
