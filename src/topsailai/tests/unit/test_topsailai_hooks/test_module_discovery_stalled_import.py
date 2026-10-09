"""Real-process lifecycle evidence for bounded module discovery."""

from __future__ import annotations

import json
from pathlib import Path

import topsailai.hooks.module_discovery as discovery
from topsailai.hooks.module_discovery_policy import ModuleDiscoveryPolicy
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    private_temp_root,
    write_module,
)


def _linux_start_identity(pid: int) -> str | None:
    """Return the Linux process start identity, or None after exact exit."""
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    except (FileNotFoundError, IndexError, OSError):
        return None


def test_real_stalled_import_reaps_group_channels_and_storage(
    tmp_path: Path, monkeypatch
) -> None:
    """A ready stalled import proves exact worker-group and channel settlement."""
    readiness = tmp_path.parent / f"{tmp_path.name}-import-ready.json"
    body = (
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        "def start_identity(pid):\n"
        "    return Path(f'/proc/{pid}/stat').read_text().split()[21]\n"
        "child = subprocess.Popen([sys.executable, '-c', 'while True: pass'])\n"
        f"Path({str(readiness)!r}).write_text(json.dumps({{"
        "'worker_pid': os.getpid(), 'worker_start': start_identity(os.getpid()), "
        "'worker_pgid': os.getpgrp(), 'child_pid': child.pid, "
        "'child_start': start_identity(child.pid), 'child_pgid': os.getpgid(child.pid)}))\n"
        "while True:\n"
        "    pass\n"
    )
    write_module(tmp_path, "alpha_stall", body)
    write_module(tmp_path, "beta_ready")
    records: list[object] = []
    backend_type = discovery.IsolatedProcessBackend

    class ObservedBackend(backend_type):
        """Retain the exact owned launch record for post-settlement assertions."""

        def _after_launch_published(self, record: object) -> None:
            records.append(record)

    monkeypatch.setattr(discovery, "IsolatedProcessBackend", ObservedBackend)
    result = discovery.build_module_manifest(
        tmp_path,
        "hook_conversation_started",
        temp_root=str(private_temp_root(tmp_path)),
        policy=ModuleDiscoveryPolicy(timeout_ms=5_000),
    )

    assert result.errors == ("module discovery timeout",)
    assert [entry.logical_name for entry in result.entries] == ["alpha_stall"]
    assert len(records) == 1
    facts = json.loads(readiness.read_text(encoding="utf-8"))
    record = records[0]
    assert record.process.pid == facts["worker_pid"]
    assert facts["worker_pgid"] == facts["worker_pid"]
    assert facts["child_pgid"] == facts["worker_pgid"]
    assert _linux_start_identity(facts["worker_pid"]) != facts["worker_start"]
    assert _linux_start_identity(facts["child_pid"]) != facts["child_start"]
    assert record.cleanup.termination_confirmed
    assert all(channel.state == "closed" for channel in record.cleanup.channels.values())
    assert all(channel.state == "closed" for channel in record.cleanup.setup_channels.values())
    assert result.recovery_owner is None
    assert not tuple(private_temp_root(tmp_path).iterdir())
