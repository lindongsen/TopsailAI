"""Complete-plan publication and exact reader ownership REDs. Author: DawsonLin."""
from dataclasses import FrozenInstanceError

import pytest

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy, ArtifactCaptureTrust
from topsailai.hooks.hook_point_plan_capture import build_hook_point_candidate
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.registry import HookRegistry
from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_capture import fixtures


def empty_candidate(tmp_path, name="point"):
    """Build a real empty complete candidate without physical resource allocation."""
    return build_hook_point_candidate(
        name, platform_policy=ExecutablePlatformPolicy("posix"),
        trust=ArtifactCaptureTrust((tmp_path,)),
        artifact_root=str(tmp_path / "absent"),
        probe_backend=IsolatedProcessBackend(temp_root=str(tmp_path)),
        policy=ArtifactCapturePolicy(),
    )


def test_empty_publication_has_typed_immutable_snapshot_and_armed_reader(tmp_path):
    """Publish exactly one default and acquire a retained immutable version."""
    from topsailai.hooks.hook_point_plan_ownership import PublishedHookPoint
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    try:
        result = registry.publish_hook_point("scope", "point", candidate)
        assert result.accepted and result.changed
        assert result.generation == registry.generation == 1
        assert type(result.snapshot) is PublishedHookPoint
        assert result.snapshot.active_version == 1
        assert result.snapshot.plan.modules == ()
        assert len(result.snapshot.plan.handlers) == 1
        assert result.snapshot.plan.default_script_hook.scripts == ()
        with pytest.raises((FrozenInstanceError, AttributeError)):
            result.snapshot.active_version = 2
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is result.snapshot
        assert registry.release_hook_point(reader) is True
        assert registry.release_hook_point(reader) is False
        owner = registry.remove_hook_point("scope", "point")
        assert owner.retire().accepted
        assert registry.acquire_hook_point("scope", "point") is None
    finally:
        candidate.close()


def test_identical_candidate_noop_preserves_point_version_and_generation(tmp_path):
    """A losing candidate must close without advancing either semantic version."""
    registry = HookRegistry()
    first, loser = empty_candidate(tmp_path), empty_candidate(tmp_path)
    try:
        initial = registry.publish_hook_point("scope", "point", first)
        repeated = registry.publish_hook_point("scope", "point", loser)
        assert initial.accepted and initial.changed
        assert repeated.accepted and not repeated.changed
        assert repeated.snapshot is initial.snapshot
        assert repeated.snapshot.active_version == 1
        assert repeated.generation == registry.generation == 1
        with pytest.raises(RuntimeError):
            _ = loser.plan
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        first.close()
        loser.close()


@pytest.mark.parametrize("scope,name", (("", "point"), ("scope", "other")))
def test_invalid_publication_leaves_initial_entry_absent(tmp_path, scope, name):
    """Scope and candidate-name rejection cannot create any active generation."""
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    try:
        result = registry.publish_hook_point(scope, name, candidate)
        assert not result.accepted and not result.changed
        assert result.snapshot is None
        assert registry.generation == 0
        assert registry.acquire_hook_point(scope, name) is None
    finally:
        assert candidate.close().accepted


def test_foreign_reader_release_cannot_consume_owning_registry_reader(tmp_path):
    """A foreign release must not consume the token or decrement its owner."""
    registry, foreign = HookRegistry(), HookRegistry()
    candidate = empty_candidate(tmp_path)
    try:
        result = registry.publish_hook_point("scope", "point", candidate)
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is result.snapshot
        assert foreign.release_hook_point(reader) is False
        assert registry.release_hook_point(reader) is True
        assert registry.release_hook_point(reader) is False
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        candidate.close()


def test_reader_retains_real_module_and_script_bytes_after_atomic_replacement(tmp_path):
    """The old complete sealed inventory survives until its exact last release."""
    build, inputs, output, imported, called = fixtures(tmp_path)
    registry = HookRegistry()
    first = build("point", **inputs)
    replacement = empty_candidate(tmp_path)
    reader = None
    try:
        initial = registry.publish_hook_point("scope", "point", first)
        reader = registry.acquire_hook_point("scope", "point")
        paths = tuple(item.captured_path for item in (
            reader.snapshot.plan.modules + reader.snapshot.plan.default_script_hook.scripts
        ))
        before = tuple(path.read_bytes() for path in paths)
        changed = registry.publish_hook_point("scope", "point", replacement)
        assert changed.accepted and changed.changed
        assert changed.snapshot.active_version == initial.snapshot.active_version + 1 == 2
        assert changed.generation == registry.generation == 2
        assert changed.previous.retire().cleanup_pending
        assert tuple(path.read_bytes() for path in paths) == before
        current = registry.acquire_hook_point("scope", "point")
        assert current.snapshot is changed.snapshot
        assert current.snapshot.plan.modules == ()
        assert len(current.snapshot.plan.handlers) == 1
        assert registry.release_hook_point(current) is True
        assert registry.release_hook_point(reader) is True
        reader = None
        assert all(not path.exists() for path in paths)
        assert imported.exists() and not called.exists()
        assert list(output.iterdir()) == []
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        if reader is not None:
            registry.release_hook_point(reader)
        first.close()
        replacement.close()


def test_legacy_publish_cannot_introduce_untyped_new_complete_entry():
    """Legacy arbitrary-plan writes must not bypass typed new-entry admission."""
    registry = HookRegistry()
    with pytest.raises((TypeError, ValueError)):
        registry.publish_configured("scope", "point", "fingerprint", object())
    assert registry.generation == 0
    assert registry.configured_plan("scope", "point") == (0, None)


def test_concurrent_identical_publications_linearize_once(tmp_path):
    """Event-synchronized contenders publish once and settle the losing owner."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    registry = HookRegistry()
    candidates = (empty_candidate(tmp_path), empty_candidate(tmp_path))
    gate = Barrier(3)

    def publish(candidate):
        """Enter publication concurrently only after both candidates are complete."""
        gate.wait(timeout=5)
        return registry.publish_hook_point("scope", "point", candidate)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(publish, candidate) for candidate in candidates)
            gate.wait(timeout=5)
            results = tuple(future.result(timeout=5) for future in futures)
        assert all(result.accepted for result in results)
        assert sum(result.changed for result in results) == 1
        assert results[0].snapshot is results[1].snapshot
        assert results[0].snapshot.active_version == 1
        assert registry.generation == 1
        losing = candidates[next(index for index, result in enumerate(results) if not result.changed)]
        with pytest.raises(RuntimeError):
            _ = losing.plan
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        for candidate in candidates:
            candidate.close()


def test_copied_token_cannot_release_exact_live_reader(tmp_path):
    """A shallow token copy has no authority over the original admission."""
    import copy
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    try:
        registry.publish_hook_point("scope", "point", candidate)
        reader = registry.acquire_hook_point("scope", "point")
        clone = copy.copy(reader)
        assert clone is not reader
        assert registry.release_hook_point(clone) is False
        assert registry.release_hook_point(reader) is True
        assert registry.release_hook_point(reader) is False
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        candidate.close()


def test_closed_candidate_rejection_preserves_exact_active_snapshot(tmp_path):
    """Rejected replacement preserves the old pointer and both version counters."""
    registry = HookRegistry()
    first, invalid = empty_candidate(tmp_path), empty_candidate(tmp_path)
    try:
        initial = registry.publish_hook_point("scope", "point", first)
        assert invalid.close().accepted
        result = registry.publish_hook_point("scope", "point", invalid)
        assert not result.accepted and not result.changed
        assert result.snapshot is initial.snapshot
        assert result.generation == registry.generation == 1
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is initial.snapshot
        assert reader.snapshot.active_version == 1
        assert registry.release_hook_point(reader) is True
        assert registry.remove_hook_point("scope", "point").retire().accepted
    finally:
        first.close()
        invalid.close()


def test_build_paused_after_module_probe_keeps_old_complete_snapshot(tmp_path, monkeypatch):
    """A real partial build cannot become visible before whole-plan publication."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import topsailai.hooks.hook_point_plan_capture as capture
    registry = HookRegistry()
    initial_candidate = empty_candidate(tmp_path)
    build, inputs, output, imported, called = fixtures(tmp_path)
    reached, resume = Event(), Event()
    original = capture._probe
    hits = []

    def pause(candidate, item, path, hook_name, deadline):
        """Pause after one real sealed Module probe, before Script mapping finishes."""
        original(candidate, item, path, hook_name, deadline)
        hits.append(item.registered_name)
        if len(hits) == 1:
            reached.set()
            assert resume.wait(5)

    def build_and_publish():
        """Publish only the completed candidate returned by the real builder."""
        candidate = build("point", **inputs)
        try:
            return registry.publish_hook_point("scope", "point", candidate)
        finally:
            candidate.close()

    try:
        initial = registry.publish_hook_point("scope", "point", initial_candidate)
        monkeypatch.setattr(capture, "_probe", pause)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(build_and_publish)
            try:
                assert reached.wait(5)
                for _ in range(20):
                    reader = registry.acquire_hook_point("scope", "point")
                    assert reader.snapshot is initial.snapshot
                    assert reader.snapshot.plan.modules == ()
                    assert len(reader.snapshot.plan.handlers) == 1
                    assert registry.release_hook_point(reader)
            finally:
                resume.set()
            changed = future.result(timeout=10)
        assert hits == ["A", "Z"]
        assert changed.changed and changed.snapshot.active_version == 2
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is changed.snapshot
        assert len(reader.snapshot.plan.modules) == 2
        assert len(reader.snapshot.plan.default_script_hook.scripts) == 2
        assert len(reader.snapshot.plan.handlers) == 3
        assert registry.release_hook_point(reader)
        assert changed.previous.retire().accepted
        assert registry.remove_hook_point("scope", "point").retire().accepted
        assert imported.exists() and not called.exists()
        assert list(output.iterdir()) == []
    finally:
        resume.set()
        initial_candidate.close()


def test_reader_is_armed_before_registry_lock_exit(tmp_path):
    """Lock-exit reentry sees a retained reader, not an unarmed returned locator."""
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    original_lock = registry._lock
    observations = []
    owner = None

    class ExitObserver:
        """Observe the real lock boundary without changing business frame state."""
        def __enter__(self):
            """Acquire the exact original Registry lock."""
            original_lock.acquire()
            return self

        def __exit__(self, *error):
            """Retire after unlock, before the acquisition returns to its caller."""
            original_lock.release()
            if not observations:
                observations.append(None)
                retired = registry.remove_hook_point("scope", "point")
                observations[0] = retired.retire()

    try:
        published = registry.publish_hook_point("scope", "point", candidate)
        registry._lock = ExitObserver()
        reader = registry.acquire_hook_point("scope", "point")
        registry._lock = original_lock
        assert reader.snapshot is published.snapshot
        assert len(observations) == 1 and observations[0].cleanup_pending
        assert registry.release_hook_point(reader)
        assert registry.acquire_hook_point("scope", "point") is None
    finally:
        registry._lock = original_lock
        candidate.close()
        if owner is not None:
            owner.retire()


def test_interrupted_retirement_keeps_exact_owner_and_cleanup_outside_lock(tmp_path, monkeypatch):
    """A close interrupt leaves physical recovery reachable and preserves identity."""
    from topsailai.hooks.artifact_store import ArtifactCaptureOwner
    registry = HookRegistry()
    build, inputs, output, imported, called = fixtures(tmp_path)
    candidate = build("point", **inputs)
    original = ArtifactCaptureOwner.close
    interrupt = KeyboardInterrupt("retirement boundary")
    hits = []

    def fail_once(capture_owner):
        """Interrupt one real close before I/O, then allow exact recovery."""
        assert registry._lock.acquire(blocking=False)
        registry._lock.release()
        hits.append(capture_owner)
        if len(hits) == 1:
            raise interrupt
        return original(capture_owner)

    owner = None
    try:
        published = registry.publish_hook_point("scope", "point", candidate)
        owner = registry.remove_hook_point("scope", "point")
        paths = tuple(item.captured_path for item in published.snapshot.plan.modules)
        monkeypatch.setattr(ArtifactCaptureOwner, "close", fail_once)
        with pytest.raises(KeyboardInterrupt) as caught:
            owner.retire()
        assert caught.value is interrupt
        assert all(path.exists() for path in paths)
        assert owner.retire().accepted
        assert len(hits) == 2 and hits[0] is hits[1]
        assert all(not path.exists() for path in paths)
        assert list(output.iterdir()) == []
    finally:
        monkeypatch.setattr(ArtifactCaptureOwner, "close", original)
        if owner is not None:
            owner.retire()
        candidate.close()


def test_execution_cleanup_token_holds_retired_inventory(tmp_path):
    """A returned reader cannot dispose bytes while exact execution cleanup remains."""
    registry = HookRegistry()
    build, inputs, output, imported, called = fixtures(tmp_path)
    candidate = build("point", **inputs)
    owner = None
    reader = None
    cleanup_token = None
    try:
        registry.publish_hook_point("scope", "point", candidate)
        reader = registry.acquire_hook_point("scope", "point")
        paths = tuple(item.captured_path for item in reader.snapshot.plan.modules)
        cleanup_token = registry.retain_hook_point_cleanup(reader)
        owner = registry.remove_hook_point("scope", "point")
        assert owner.retire().cleanup_pending
        assert registry.release_hook_point(reader)
        reader = None
        assert all(path.exists() for path in paths)
        import copy
        assert not registry.release_hook_point_cleanup(copy.copy(cleanup_token))
        assert not HookRegistry().release_hook_point_cleanup(cleanup_token)
        assert all(path.exists() for path in paths)
        assert registry.release_hook_point_cleanup(cleanup_token)
        assert not registry.release_hook_point_cleanup(cleanup_token)
        cleanup_token = None
        assert all(not path.exists() for path in paths)
        assert list(output.iterdir()) == []
    finally:
        if reader is not None:
            registry.release_hook_point(reader)
        if cleanup_token is not None:
            registry.release_hook_point_cleanup(cleanup_token)
        if owner is not None:
            owner.retire()
        candidate.close()


def test_transferred_candidate_cannot_close_live_publication(tmp_path):
    """Former candidate cleanup calls cannot destroy a retained published inventory."""
    registry = HookRegistry()
    build, inputs, output, imported, called = fixtures(tmp_path)
    candidate = build("point", **inputs)
    reader = None
    owner = None
    try:
        result = registry.publish_hook_point("scope", "point", candidate)
        assert result.accepted
        reader = registry.acquire_hook_point("scope", "point")
        paths = tuple(item.captured_path for item in reader.snapshot.plan.modules)
        original = tuple(path.read_bytes() for path in paths)
        assert candidate.close().accepted
        assert not candidate.retry_cleanup("foreign-debt")
        with pytest.raises(RuntimeError):
            _ = candidate.plan
        assert tuple(path.read_bytes() for path in paths) == original
        owner = registry.remove_hook_point("scope", "point")
        assert owner.retire().cleanup_pending
        assert registry.release_hook_point(reader)
        reader = None
        assert all(not path.exists() for path in paths)
        assert list(output.iterdir()) == []
    finally:
        if reader is not None:
            registry.release_hook_point(reader)
        if owner is not None:
            owner.retire()
        candidate.close()


def test_owner_cannot_replace_canonical_snapshot(tmp_path):
    """Ordinary owner assignment cannot bypass validated publication or point versions."""
    from dataclasses import replace
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    published = registry.publish_hook_point("scope", "point", candidate)
    _, owner = registry.configured_plan("scope", "point")
    try:
        with pytest.raises(AttributeError):
            owner.snapshot = published.snapshot
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is published.snapshot
        assert registry.generation == 1
        assert registry.release_hook_point(reader)
    finally:
        registry.remove_hook_point("scope", "point").retire()


def test_native_owner_snapshot_substitution_cannot_change_admission(tmp_path):
    """Native instance writes must not replace the validated canonical publication."""
    from dataclasses import replace
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    result = registry.publish_hook_point("scope", "point", candidate)
    _, owner = registry.configured_plan("scope", "point")
    try:
        from topsailai.hooks.hook_point_plan_ownership import PublishedHookPoint
        forged = PublishedHookPoint(result.snapshot.plan, 999)
        try:
            object.__setattr__(owner, "_snapshot", forged)
        except AttributeError:
            pass
        reader = registry.acquire_hook_point("scope", "point")
        try:
            assert reader.snapshot is result.snapshot
            assert reader.snapshot.active_version == 1
            assert registry.generation == 1
        finally:
            registry.release_hook_point(reader)
    finally:
        registry.remove_hook_point("scope", "point").retire()


@pytest.mark.parametrize("target", ("plan", "terminal", "options", "policy", "shadow"))
def test_native_observer_mutation_cannot_rewrite_publication(tmp_path, target):
    """Mutable native observation surfaces never become canonical publication input."""
    registry = HookRegistry()
    result = registry.publish_hook_point("scope", "point", empty_candidate(tmp_path))
    _, owner = registry.configured_plan("scope", "point")
    try:
        observed = result.snapshot.plan
        if target == "plan":
            object.__setattr__(observed, "hook_point_name", "forged")
        elif target == "terminal":
            object.__setattr__(observed.default_script_hook, "configured", True)
        elif target == "options":
            object.__setattr__(observed.options, "argv", ("forged",))
        elif target == "policy":
            object.__setattr__(observed.execution_policy, "entry_timeout_ms", 1)
        else:
            owner.__dict__["_snapshot"] = None
            owner.__dict__["snapshot"] = None
        reader = registry.acquire_hook_point("scope", "point")
        try:
            plan = reader.snapshot.plan
            assert reader.snapshot is result.snapshot
            assert plan.hook_point_name == "point"
            assert not plan.default_script_hook.configured
            assert plan.options.argv == ()
            assert plan.execution_policy.entry_timeout_ms == 1000
            assert registry.generation == 1
        finally:
            registry.release_hook_point(reader)
    finally:
        registry.remove_hook_point("scope", "point").retire()


def test_native_module_and_invocation_backing_mutation_is_detached(tmp_path):
    """Native child/backing writes cannot change later reader locator or invocation."""
    registry = HookRegistry()
    build, inputs, output, imported, called = fixtures(tmp_path)
    candidate = build("point", **inputs)
    result = registry.publish_hook_point("scope", "point", candidate)
    try:
        observed = result.snapshot.plan.modules[0]
        expected_path = observed.captured_path
        object.__setattr__(observed, "captured_path", tmp_path / "foreign")
        object.__setattr__(observed.identity, "name", "forged")
        object.__setattr__(observed.source, "enabled", False)
        observed.invocation.kwargs._FrozenJsonObject__values["forged"] = True
        reader = registry.acquire_hook_point("scope", "point")
        try:
            actual = reader.snapshot.plan.modules[0]
            assert actual.captured_path == expected_path
            assert actual.identity.name == "A"
            assert actual.source.enabled
            assert dict(actual.invocation.kwargs) == {}
            assert actual.captured_path.exists()
        finally:
            registry.release_hook_point(reader)
    finally:
        registry.remove_hook_point("scope", "point").retire()


def test_different_candidate_writers_linearize_exact_versions(tmp_path):
    """Different fully built contenders linearize once each by Registry publish order."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    registry = HookRegistry()
    first = empty_candidate(tmp_path)
    build, inputs, output, imported, called = fixtures(tmp_path)
    second = build("point", **inputs)
    gate = Barrier(3)

    def publish(candidate):
        """Start two real writers at one barrier without assuming scheduler order."""
        gate.wait(timeout=5)
        return registry.publish_hook_point("scope", "point", candidate)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(publish, item) for item in (first, second)]
            gate.wait(timeout=5)
            results = [future.result(timeout=5) for future in futures]
        ordered = sorted(results, key=lambda result: result.generation)
        assert all(result.accepted and result.changed for result in results)
        assert [result.generation for result in ordered] == [1, 2]
        assert [result.snapshot.active_version for result in ordered] == [1, 2]
        _, current = registry.configured_plan("scope", "point")
        assert current.snapshot is ordered[1].snapshot
        assert ordered[1].previous.snapshot is ordered[0].snapshot
        assert ordered[1].previous.retire().accepted
        reader = registry.acquire_hook_point("scope", "point")
        assert reader.snapshot is ordered[1].snapshot
        assert registry.release_hook_point(reader)
    finally:
        current = registry.remove_hook_point("scope", "point")
        if current is not None:
            current.retire()
        first.close()
        second.close()


def test_canonical_copies_stale_owner_and_typed_legacy_guards(tmp_path):
    """Equal/copied observers and stale ownership cannot mint new publication rights."""
    import copy
    from topsailai.hooks.hook_point_plan_ownership import PublishedHookPoint
    registry = HookRegistry()
    candidate = empty_candidate(tmp_path)
    result = registry.publish_hook_point("scope", "point", candidate)
    _, owner = registry.configured_plan("scope", "point")
    reader = registry.acquire_hook_point("scope", "point")
    try:
        copied = copy.copy(result.snapshot)
        with pytest.raises(ValueError):
            _ = copied.plan
        for plan, version in ((None, 1), (result.snapshot.plan, True), (result.snapshot.plan, 0)):
            with pytest.raises(ValueError):
                PublishedHookPoint(plan, version)
        assert not registry.publish_hook_point("scope", "point", candidate).accepted
        assert owner.retain_cleanup(copy.copy(reader)) is None
        assert registry.retain_hook_point_cleanup(object()) is None
        assert registry.release_hook_point_cleanup(object()) is False
        assert not owner.retry_cleanup("foreign")
        assert registry.release_hook_point(reader)
        assert registry.remove_hook_point("scope", "point") is owner
        assert owner.retire().accepted
        assert owner.acquire() is None
        assert not owner.retry_cleanup("foreign")
        legacy = empty_candidate(tmp_path)
        changed, generation, previous = registry.publish_configured(
            "scope", "point", legacy.plan.fingerprint, legacy)
        assert changed and previous is None and generation == 3
        rejected = empty_candidate(tmp_path)
        try:
            with pytest.raises(ValueError):
                registry.publish_configured("scope", "other", rejected.plan.fingerprint, rejected)
        finally:
            rejected.close()
    finally:
        registry.release_hook_point(reader)
        current = registry.remove_hook_point("scope", "point")
        if current is not None:
            current.retire()


@pytest.mark.parametrize("mutation", ("native", "dictionary"))
def test_candidate_foreign_capture_plan_cannot_publish(tmp_path, mutation):
    """A genuine candidate cannot borrow another capture's semantic locators."""
    build, inputs, output, imported, called = fixtures(tmp_path)
    candidate, foreign = build("point", **inputs), build("point", **inputs)
    original_plan = candidate.plan
    foreign_plan = foreign.plan
    registry = HookRegistry()
    owner = None
    try:
        if mutation == "native":
            object.__setattr__(candidate, "_plan", foreign_plan)
        else:
            candidate.__dict__["_plan"] = foreign_plan
        result = registry.publish_hook_point("scope", "point", candidate)
        owner = registry.configured_plan("scope", "point")[1]
        assert not result.accepted
        assert registry.generation == 0 and owner is None
        assert all(item.captured_path.exists() for item in foreign_plan.modules)
    finally:
        if owner is not None:
            registry.remove_hook_point("scope", "point")
            owner.retire()
        else:
            object.__setattr__(candidate, "_plan", original_plan)
            candidate.close()
        foreign.close()
