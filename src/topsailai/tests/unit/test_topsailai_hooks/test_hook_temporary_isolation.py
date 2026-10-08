"""Acceptance tests for host-owned module-discovery temporary storage."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import pwd
import subprocess
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import topsailai.hooks.module_discovery as discovery_module
from topsailai.hooks.temporary_storage import TemporaryStorageOwner
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import (
    private_temp_root,
    write_module,
)


def _inventory(root: Path) -> dict[str, str]:
    """Return the complete regular-file inventory and content hashes."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_temp_root_is_required_keyword_only_and_invalid_roots_reject(tmp_path: Path) -> None:
    """The API has no positional or implicit temporary-storage fallback."""
    signature = inspect.signature(discovery_module.build_module_manifest)
    assert signature.parameters["temp_root"].kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        discovery_module.build_module_manifest(tmp_path, "hook_conversation_started")
    with pytest.raises(TypeError):
        discovery_module.build_module_manifest(tmp_path, "hook_conversation_started", str(tmp_path))

    valid_root = tmp_path.parent / f"{tmp_path.name}-valid-temp"
    valid_root.mkdir(mode=0o700)
    insecure_root = tmp_path.parent / f"{tmp_path.name}-insecure-temp"
    insecure_root.mkdir(mode=0o755)
    symlink_root = tmp_path.parent / f"{tmp_path.name}-symlink-temp"
    symlink_root.symlink_to(valid_root, target_is_directory=True)
    values = (
        None,
        tmp_path,
        "relative",
        str(tmp_path / "missing"),
        str(tmp_path),
        str(insecure_root),
        str(symlink_root),
    )
    for value in values:
        result = discovery_module.build_module_manifest(
            tmp_path, "hook_conversation_started", temp_root=value
        )
        assert not result.accepted
        assert result.errors == ("invalid discovery temp root",)


def test_success_removes_only_owned_invocation_directory(tmp_path: Path) -> None:
    """Successful discovery preserves source inventory and host-owned siblings."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    sentinel = host_root / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    before = _inventory(plugins)

    result = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert result.accepted
    assert result.recovery_owner is None
    assert _inventory(plugins) == before
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert [path.name for path in host_root.iterdir()] == ["keep.txt"]


def test_concurrent_discoveries_use_distinct_invocation_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent calls never share their backend working directory."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    observed: list[str] = []
    original_init = discovery_module.IsolatedProcessBackend.__init__

    def record_init(self, *, temp_root: str, **kwargs: object) -> None:
        observed.append(temp_root)
        original_init(self, temp_root=temp_root, **kwargs)

    monkeypatch.setattr(discovery_module.IsolatedProcessBackend, "__init__", record_init)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _: discovery_module.build_module_manifest(
                    plugins, "hook_conversation_started", temp_root=str(host_root)
                ),
                range(2),
            )
        )

    assert all(result.accepted for result in results)
    assert len(set(observed)) == 2
    assert not tuple(path for path in host_root.iterdir() if path.name.startswith("discovery-"))


def test_storage_cleanup_failure_is_queryable_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A removal failure retains exact debt until a successful retry."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    original_cleanup = TemporaryStorageOwner.cleanup
    calls = 0

    def fail_once(self: TemporaryStorageOwner) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            self.retain_cleanup_debt()
            return False
        return original_cleanup(self)

    monkeypatch.setattr(TemporaryStorageOwner, "cleanup", fail_once)
    result = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert result.recovery_owner is not None
    debts = result.recovery_owner.cleanup_debts()
    assert len(debts) == 1 and debts[0].pid is None
    assert result.recovery_owner.retry_cleanup(debts[0].debt_id)
    assert result.recovery_owner.cleanup_debts() == ()
    assert not tuple(host_root.iterdir())


def test_import_failure_and_timeout_remove_owned_storage(tmp_path: Path) -> None:
    """Ordinary load failure and timeout settle before removing invocation storage."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    host_root = private_temp_root(plugins)
    write_module(plugins, "broken", "raise RuntimeError('sentinel')\n")

    failed = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert failed.entries[0].load_status == "load_error"
    assert failed.recovery_owner is None
    assert not tuple(host_root.iterdir())

    (plugins / "broken.py").unlink()
    write_module(plugins, "slow", "while True:\n    pass\n")
    timed_out = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert timed_out.entries[0].load_status == "load_error"
    assert timed_out.recovery_owner is None
    assert not tuple(host_root.iterdir())


def test_host_interruption_preserves_identity_when_storage_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup uncertainty attaches recovery without replacing an interruption."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("sentinel")

    class InterruptingBackend:
        """Raise one controlled host interruption without process debt."""

        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> object:
            raise interruption

        def cleanup_debts(self) -> tuple[object, ...]:
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    def fail_cleanup(self: TemporaryStorageOwner) -> bool:
        self.retain_cleanup_debt()
        return False

    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", InterruptingBackend)
    monkeypatch.setattr(TemporaryStorageOwner, "cleanup", fail_cleanup)

    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    owner = discovery_module.get_interruption_recovery_owner(caught.value)
    assert owner is not None
    debts = owner.cleanup_debts()
    assert len(debts) == 1 and debts[0].pid is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux permission contract")
def test_read_only_plugin_inventory_is_unchanged_for_worker_identity(tmp_path: Path) -> None:
    """A nonprivileged worker discovers a truly read-only plugin tree without writes."""
    if os.geteuid() != 0:
        pytest.skip("requires root to establish a distinct nonprivileged worker identity")
    account = pwd.getpwnam("nobody")
    plugins = tmp_path / "plugins"
    plugins.mkdir(mode=0o755)
    write_module(
        plugins,
        "valid",
        "import tempfile\n"
        "with tempfile.NamedTemporaryFile() as stream:\n"
        "    stream.write(b'ok')\n"
        "def main(*args, **kwargs):\n"
        "    return None\n",
    )
    plugins.chmod(0o555)
    host_root = tmp_path / "host-temp"
    host_root.mkdir(mode=0o700)
    os.chown(host_root, account.pw_uid, account.pw_gid)
    agent_home = tmp_path / "agent-home"
    agent_home.mkdir(mode=0o700)
    os.chown(agent_home, account.pw_uid, account.pw_gid)
    os.chown(tmp_path, account.pw_uid, account.pw_gid)
    tmp_path.chmod(0o755)
    tmp_path.parent.chmod(0o755)
    before = _inventory(plugins)
    script = (
        "import json, pathlib; "
        "from topsailai.hooks.module_discovery import build_module_manifest; "
        f"p=pathlib.Path({str(plugins)!r}); "
        "write_failed=False; "
        "\ntry: (p/'forbidden').write_text('x')\n"
        "except PermissionError: write_failed=True\n"
        f"r=build_module_manifest(p, 'hook_conversation_started', temp_root={str(host_root)!r}); "
        "print(json.dumps({'accepted':r.accepted,'ready':r.entries[0].entry_valid,"
        "'write_failed':write_failed}))"
    )

    completed = subprocess.run(
        [sysconfig.get_config_var("BINDIR") + "/python3", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": "/TopsailAI/src",
            "TOPSAILAI_HOME": str(agent_home),
            "HOME": str(agent_home),
        },
        user=account.pw_uid,
        group=account.pw_gid,
    )

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout.splitlines()[-1])
    assert evidence == {"accepted": True, "ready": True, "write_failed": True}
    assert _inventory(plugins) == before
    assert not tuple(host_root.iterdir())


def test_allocation_failure_retains_storage_only_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-creation allocation failure returns exact residual ownership."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)

    monkeypatch.setattr(Path, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(
        discovery_module.shutil if hasattr(discovery_module, "shutil") else __import__(
            "topsailai.hooks.temporary_storage", fromlist=["shutil"]
        ).shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError()),
    )

    result = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert not result.accepted
    assert result.errors == ("module discovery cleanup pending",)
    assert result.recovery_owner is not None
    debts = result.recovery_owner.cleanup_debts()
    assert len(debts) == 1 and debts[0].state == "storage"


def test_backend_construction_failure_cleans_or_retains_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage remains recoverable before backend ownership exists."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("constructor")

    def interrupt_backend(*args: object, **kwargs: object) -> object:
        raise interruption

    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", interrupt_backend)
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["shutil"])
    monkeypatch.setattr(
        storage_module.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError()),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    owner = discovery_module.get_interruption_recovery_owner(caught.value)
    assert owner is not None
    assert len(owner.cleanup_debts()) == 1


def test_cleanup_interruption_preserves_recovery_and_primary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage cleanup interruption never erases recovery or a primary interrupt."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["shutil"])
    cleanup_interrupt = KeyboardInterrupt("cleanup")
    monkeypatch.setattr(
        storage_module.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(cleanup_interrupt),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is cleanup_interrupt
    assert discovery_module.get_interruption_recovery_owner(caught.value) is not None

    primary = KeyboardInterrupt("primary")

    class InterruptingBackend:
        def __init__(self, *, temp_root: str) -> None:
            self.temp_root = temp_root

        def execute(self, handler_ref: str, context: object, timeout_ms: int) -> object:
            raise primary

        def cleanup_debts(self) -> tuple[object, ...]:
            return ()

        def retry_cleanup(self, debt_id: str) -> bool:
            return False

    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", InterruptingBackend)
    with pytest.raises(KeyboardInterrupt) as primary_caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )
    assert primary_caught.value is primary
    assert discovery_module.get_interruption_recovery_owner(primary) is not None


def test_deleted_storage_settles_despite_log_failure_and_missing_retry_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deletion fact is authoritative when logging fails or the path is already absent."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    host_root.chmod(0o700)
    owner = TemporaryStorageOwner(host_root)
    assert owner.allocate()
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: (_ for _ in ()).throw(BrokenPipeError()))
    assert owner.cleanup()
    assert owner.cleanup_debts() == ()

    second = TemporaryStorageOwner(host_root)
    assert second.allocate()
    debt_path = second.path
    second.retain_cleanup_debt()
    debt_id = second.cleanup_debts()[0].debt_id
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["shutil"])
    storage_module.shutil.rmtree(debt_path)
    assert second.retry_cleanup(debt_id)
    assert second.cleanup_debts() == ()


def test_directory_creation_handoff_interruption_preserves_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uncertain creation retains debt without inferring deletion authority."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("created")
    original_mkdir = os.mkdir

    def interrupt_after_mkdir(path: object, mode: int = 0o777, *args: object, **kwargs: object) -> None:
        original_mkdir(path, mode, *args, **kwargs)
        raise interruption

    monkeypatch.setattr(os, "mkdir", interrupt_after_mkdir)
    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    owner = discovery_module.get_interruption_recovery_owner(interruption)
    assert owner is not None
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    created = tuple(host_root.iterdir())
    assert len(created) == 1
    created[0].rmdir()
    assert owner.retry_cleanup(debts[0].debt_id)
    assert owner.cleanup_debts() == ()


def test_backend_owner_handoff_interruption_preserves_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A constructed backend remains inside the storage lifecycle guard."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("owner handoff")
    original_factory = discovery_module._make_cleanup_owner
    calls = 0

    def interrupt_second_owner(backend: object, storage: TemporaryStorageOwner) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise interruption
        return original_factory(backend, storage)

    monkeypatch.setattr(discovery_module, "_make_cleanup_owner", interrupt_second_owner)
    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    assert not tuple(host_root.iterdir())


def test_post_probe_manifest_handoff_interruption_preserves_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed probe remains protected until manifest ownership is settled."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)
    interruption = KeyboardInterrupt("manifest handoff")

    def interrupt_append(entries: object, entry: object) -> None:
        raise interruption

    monkeypatch.setattr(discovery_module, "_append_manifest_entry", interrupt_append)
    with pytest.raises(KeyboardInterrupt) as caught:
        discovery_module.build_module_manifest(
            plugins, "hook_conversation_started", temp_root=str(host_root)
        )

    assert caught.value is interruption
    assert not tuple(host_root.iterdir())


def test_collision_before_mkdir_interruption_never_deletes_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate interruption cannot grant deletion authority over a collision."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    collision = host_root / "discovery-fixed"
    collision.mkdir()
    sentinel = collision / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    interruption = KeyboardInterrupt("before mkdir")
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["uuid"])

    class FixedUUID:
        hex = "fixed"

    owner = TemporaryStorageOwner(host_root)
    monkeypatch.setattr(storage_module.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(
        storage_module,
        "_before_directory_create",
        lambda path: (_ for _ in ()).throw(interruption),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.allocate()

    assert caught.value is interruption
    assert owner.cleanup()
    assert owner.retry_cleanup("non-owned-candidate")
    assert owner.cleanup_debts() == ()
    assert collision.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_collision_withdrawal_interruption_never_deletes_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collision interruption before withdrawal keeps the candidate non-owned."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    collision = host_root / "discovery-fixed"
    collision.mkdir()
    sentinel = collision / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")
    interruption = KeyboardInterrupt("after collision")
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["uuid"])

    class FixedUUID:
        hex = "fixed"

    owner = TemporaryStorageOwner(host_root)
    monkeypatch.setattr(storage_module.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(
        storage_module,
        "_after_directory_collision",
        lambda path: (_ for _ in ()).throw(interruption),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.allocate()

    assert caught.value is interruption
    assert owner.cleanup()
    assert owner.retry_cleanup("non-owned-candidate")
    assert owner.cleanup_debts() == ()
    assert collision.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_chmod_file_exists_error_cleans_created_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A post-create FileExistsError remains an owned allocation failure."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    write_module(plugins, "valid")
    host_root = private_temp_root(plugins)

    monkeypatch.setattr(
        Path,
        "chmod",
        lambda self, mode: (_ for _ in ()).throw(FileExistsError()),
    )

    result = discovery_module.build_module_manifest(
        plugins, "hook_conversation_started", temp_root=str(host_root)
    )

    assert not result.accepted
    assert result.errors == ("invalid discovery temp root",)
    assert result.recovery_owner is None
    assert not tuple(host_root.iterdir())


def test_late_collision_during_interrupted_create_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory appearing at an uncertain create boundary stays non-owned."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["uuid"])
    collision = host_root / "discovery-fixed"
    sentinel = collision / "sentinel"
    interruption = KeyboardInterrupt("uncertain collision")
    original_mkdir = storage_module.os.mkdir

    class FixedUUID:
        hex = "fixed"

    def create_other_then_interrupt(path: object, mode: int = 0o777) -> None:
        original_mkdir(path, mode)
        sentinel.write_text("keep", encoding="utf-8")
        raise interruption

    owner = TemporaryStorageOwner(host_root)
    monkeypatch.setattr(storage_module.uuid, "uuid4", lambda: FixedUUID())
    monkeypatch.setattr(storage_module.os, "mkdir", create_other_then_interrupt)

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.allocate()

    assert caught.value is interruption
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    assert not owner.cleanup()
    assert not owner.retry_cleanup(debts[0].debt_id)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_partial_claim_interruption_preserves_identity_and_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted ownership promotion completes debt without replacing the interrupt."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["uuid"])
    interruption = KeyboardInterrupt("partial claim")
    owner = TemporaryStorageOwner(host_root)
    monkeypatch.setattr(
        storage_module,
        "_after_candidate_promoted",
        lambda path: (_ for _ in ()).throw(interruption),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.allocate()

    assert caught.value is interruption
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    assert owner.retry_cleanup(debts[0].debt_id)
    assert owner.cleanup_debts() == ()
    assert not tuple(host_root.iterdir())


def test_interrupted_create_with_failed_recovery_check_retains_safe_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uncertain creation remains recoverable when filesystem inspection fails."""
    host_root = tmp_path / "host"
    host_root.mkdir(mode=0o700)
    storage_module = __import__("topsailai.hooks.temporary_storage", fromlist=["uuid"])
    interruption = KeyboardInterrupt("created but unconfirmed")
    original_mkdir = storage_module.os.mkdir

    def create_then_interrupt(path: object, mode: int = 0o777) -> None:
        original_mkdir(path, mode)
        raise interruption

    owner = TemporaryStorageOwner(host_root)
    monkeypatch.setattr(storage_module.os, "mkdir", create_then_interrupt)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda self: (_ for _ in ()).throw(OSError("inspection unavailable")),
    )

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.allocate()

    assert caught.value is interruption
    debts = owner.cleanup_debts()
    assert len(debts) == 1
    assert not owner.cleanup()
    assert not owner.retry_cleanup(debts[0].debt_id)
    monkeypatch.undo()
    created = tuple(host_root.iterdir())
    assert len(created) == 1
    created[0].rmdir()
    assert owner.retry_cleanup(debts[0].debt_id)
    assert owner.cleanup_debts() == ()
