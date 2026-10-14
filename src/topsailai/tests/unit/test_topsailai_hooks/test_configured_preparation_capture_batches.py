"""Passive capture batching regressions. Author: DawsonLin."""

from pathlib import Path

import pytest

def test_capture_batches_have_independent_shards_and_stop_after_failure(monkeypatch):
    """Each consecutive batch owns one manager and a failed batch has no successor."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = SimpleNamespace(index=self.index)
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            if self.index == 1:
                return SimpleNamespace(accepted=False, lease=None, errors=("failure",))
            entries = tuple(SimpleNamespace(index=i, kind=req.kind, logical_name=req.logical_name,
                validation=SimpleNamespace(source_path=req.source_path), relative_path=f"{i}.bin") for i, req in enumerate(requests))
            lease = SimpleNamespace(entries=entries, directory=Path("/capture"), total_bytes=len(requests), identity=f"lease-{self.index}")
            return SimpleNamespace(accepted=True, lease=lease, errors=())

        def close(self, *, deadline):
            return SimpleNamespace(accepted=True, cleanup_pending=False)

    class FakeRoot:
        def revalidate(self):
            return None

    class FakeOwnership:
        root_owner = FakeRoot()
        shards = []

        def register_shard(self, shard):
            self.shards.append(shard)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: self)
    works = tuple(preparation._ModuleWork(0, SimpleNamespace(), Path("/src"), SimpleNamespace(source_path=Path(f"/src/{i}"), kind="python_source", logical_name=str(i))) for i in range(256))
    ownership = FakeOwnership()
    budget = preparation._PreparationBudget(max_scanned_entries=1000, max_candidates=1000, max_artifact_bytes=1000)
    operation = SimpleNamespace(deadline=10**12, checkpoint=lambda: None)

    with pytest.raises(preparation._PreparationRejected, match="artifact_rejected"):
        preparation._capture_work_sequence(works, ownership, Path("/artifacts"), operation, budget, None, None)

    assert len(FakeManager.instances) == 2
    assert [len(shard.leases) for shard in ownership.shards] == [1, 0]


@pytest.mark.parametrize(
    ("work_count", "expected_shapes"),
    ((129, (128, 1)), (256, (128, 128)), (1024, (128,) * 8)),
)
def test_capture_work_sequence_uses_exact_bounded_shard_shapes(monkeypatch, tmp_path, work_count, expected_shapes):
    """Global capture uses one independent shard for every consecutive batch."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = SimpleNamespace(index=self.index)
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            capture_root = kwargs.pop("capture_root", None)
            directory = tmp_path / f"capture-{self.index}"
            directory.mkdir(parents=True, exist_ok=True)
            entries = tuple(
                SimpleNamespace(
                    index=index,
                    kind=request.kind,
                    logical_name=request.logical_name,
                    validation=SimpleNamespace(source_path=request.source_path),
                    relative_path=f"{self.index}-{index}.bin",
                )
                for index, request in enumerate(requests)
            )
            for entry in entries:
                (directory / entry.relative_path).write_bytes(b"x")
            return SimpleNamespace(
                accepted=True,
                lease=SimpleNamespace(
                    entries=entries,
                    directory=directory,
                    total_bytes=len(entries),
                    identity=f"lease-{self.index}",
                ),
                errors=(),
            )

        def close(self, *, deadline):
            return SimpleNamespace(accepted=True, cleanup_pending=False)

    class FakeRoot:
        def revalidate(self):
            return None

    class FakeOwnership:
        root_owner = FakeRoot()

        def __init__(self):
            self.shards = []

        def register_shard(self, shard):
            self.shards.append(shard)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    base = tmp_path / "shard-shapes"
    base.mkdir(parents=True, exist_ok=True)
    works = tuple(
        preparation._ModuleWork(
            0,
            SimpleNamespace(),
            Path("/src"),
            SimpleNamespace(
                source_path=Path(f"/src/{index}.py"),
                kind="python_source",
                logical_name=str(index),
            ),
        )
        for index in range(work_count)
    )
    ownership = FakeOwnership()
    budget = preparation._PreparationBudget(
        max_scanned_entries=work_count + 1,
        max_candidates=work_count + 1,
        max_artifact_bytes=work_count + 1,
    )
    operation = SimpleNamespace(deadline=10**12, checkpoint=lambda: None)

    captured = preparation._capture_work_sequence(
        works, ownership, base, operation, budget, None, None
    )

    assert len(captured) == work_count
    assert tuple(len(shard.leases[0].entries) for shard in ownership.shards) == expected_shapes
    assert tuple(manager.index for manager in FakeManager.instances) == tuple(range(len(expected_shapes)))


def test_capture_work_sequence_rejects_before_ninth_shard(monkeypatch):
    """Capacity rejects 1025 work items before allocating a ninth manager."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class NeverManager:
        instances = []

        def __init__(self, **kwargs):
            type(self).instances.append(self)

    monkeypatch.setattr(preparation, "ArtifactLeaseManager", NeverManager)
    configuration = SimpleNamespace()
    operation = SimpleNamespace(checkpoint=lambda: None)
    budget = preparation._PreparationBudget(
        max_scanned_entries=2000, max_candidates=2000, max_artifact_bytes=2000
    )
    with pytest.raises(preparation._PreparationRejected, match="capacity_exceeded"):
        preparation._capture_work_sequence(
            tuple(
                preparation._ModuleWork(
                    0, configuration, Path("/src"),
                    SimpleNamespace(
                        source_path=Path(f"/src/{index}.py"),
                        kind="python_source", logical_name=str(index),
                    ),
                ) for index in range(1025)
            ),
            SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), register_shard=lambda shard: None),
            Path("/artifacts"), operation, budget, None, None,
        )
    assert NeverManager.instances == []


def test_capture_work_sequence_cancellation_stops_batch_three(monkeypatch, tmp_path):
    """A cancellation checkpoint after batch two prevents a third shard."""
    from types import SimpleNamespace
    from topsailai.hooks import configured_preparation as preparation

    class FakeManager:
        instances = []

        def __init__(self, **kwargs):
            self.index = len(type(self).instances)
            self.group = object()
            type(self).instances.append(self)

        def begin_candidate(self, *, deadline):
            return SimpleNamespace(accepted=True, group=self.group)

        def capture(self, group, requests, **kwargs):
            directory = tmp_path / f"cancel-{self.index}"
            directory.mkdir(parents=True, exist_ok=True)
            entries = tuple(SimpleNamespace(index=index, kind=request.kind, logical_name=request.logical_name, validation=SimpleNamespace(source_path=request.source_path), relative_path=f"{index}.bin") for index, request in enumerate(requests))
            for entry in entries:
                (directory / entry.relative_path).write_bytes(b"x")
            return SimpleNamespace(accepted=True, lease=SimpleNamespace(entries=entries, directory=directory, total_bytes=len(entries), identity=str(self.index)), errors=())

    class Operation:
        deadline = 10**12
        def __init__(self):
            self.checkpoints = 0
        def checkpoint(self):
            self.checkpoints += 1
            if self.checkpoints == 5:
                raise preparation._PreparationRejected("cancelled")

    ownership = SimpleNamespace(root_owner=SimpleNamespace(revalidate=lambda: None), shards=[], register_shard=lambda shard: ownership.shards.append(shard))
    monkeypatch.setattr(preparation, "ArtifactLeaseManager", FakeManager)
    monkeypatch.setattr(preparation, "artifact_capture_trust", lambda trust: trust)
    works = tuple(preparation._ModuleWork(0, SimpleNamespace(), Path("/src"), SimpleNamespace(source_path=Path(f"/src/{i}"), kind="python_source", logical_name=str(i))) for i in range(384))
    budget = preparation._PreparationBudget(max_scanned_entries=1000, max_candidates=1000, max_artifact_bytes=1000)
    with pytest.raises(preparation._PreparationRejected, match="cancelled"):
        preparation._capture_work_sequence(works, ownership, Path("/artifacts"), Operation(), budget, None, None)
    assert len(FakeManager.instances) == 2
