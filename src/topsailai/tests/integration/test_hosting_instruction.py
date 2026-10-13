"""Real supervised instruction lifecycle. Author: DawsonLin."""

from contextlib import contextmanager
import json
import time

from topsailai.scripts import start_script
from topsailai.workspace.plugin_instruction.hosting import HostingController, hosting


def test_real_hosting_process(tmp_path):
    """Return before child exit, preserve argv, then reap the exact child."""
    output = tmp_path / "argv.json"
    script = tmp_path / "child.py"
    script.write_text("import sys,json,time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\ntime.sleep(60)\n")
    script.chmod(0o755)
    children = []

    @contextmanager
    def launcher(path, args):
        """Redirect the exact production call to an isolated real child."""
        assert path == "session_agent_driver/session_agent_driver"
        with start_script(script, [str(output), *args], cwd=tmp_path, shutdown_timeout=0.2) as child:
            children.append(child)
            yield child

    controller = HostingController(launcher=launcher)
    try:
        assert "started" in hosting(session_id="isolated-session", controller=controller)
        assert children[0].poll() is None
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert json.loads(output.read_text()) == ["--session", "isolated-session"]
    finally:
        controller.close()
    assert children[0].returncode is not None
    assert children[0].wait(timeout=1) == children[0].returncode
    assert not controller._launch.thread.is_alive()


def test_extensionless_driver_help(tmp_path, capfd):
    """Resolve the real driver without touching live sessions or external LLM."""
    home = tmp_path / "home"
    home.mkdir()
    with start_script("session_agent_driver/session_agent_driver", ["--help"],
                      cwd=tmp_path, env={"TOPSAILAI_HOME": str(home),
                      "TOPSAILAI_EVENTS_ENABLED": "0", "TMPDIR": str(tmp_path),
                      "PYTHONDONTWRITEBYTECODE": "1"}) as child:
        assert child.wait(timeout=30) == 0
    assert "--session" in capfd.readouterr().out
