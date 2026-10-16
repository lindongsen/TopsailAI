"""Adapters from selected inventories to the existing preparation work model."""

from __future__ import annotations
import stat
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.artifact_contracts import ArtifactCapturePolicy
from topsailai.hooks.artifact_validation import file_identity
from topsailai.hooks.configured_resource_sources import (
    SelectedResourceEntry,
    SelectedResourceRejected,
    _has_symlink_ancestry,
    build_selected_inventory,
)
from topsailai.hooks.hook_script_contracts import HookScriptExecutionOptions, HookScriptExecutionPolicy
from topsailai.hooks.hook_script_discovery import HookScriptEntry, ExecutablePlatformPolicy
from topsailai.hooks.module_discovery import ModuleCandidate


class _ExecutablePlanRejected(Exception):
    """Carry one explicit executable-plan rejection to orchestration."""

    def __init__(self, token: str) -> None:
        if token not in {"binding_conflict", "artifact_rejected"}:
            raise ValueError(token)
        self.token = token
        super().__init__(token)


@dataclass(frozen=True, slots=True)
class _ModuleWork:
    """Bind one Hook module to its original candidate."""

    hook_index: int
    point: object
    inventory_root: Path
    candidate: ModuleCandidate
    selected: SelectedResourceEntry | None = None


@dataclass(frozen=True, slots=True)
class _ScriptWork:
    """Bind one terminal Hook script to its capture request."""

    hook_index: int
    point: object
    entry: HookScriptEntry
    selected: SelectedResourceEntry | None = None


def _selected_identity(path: Path, operation):
    """Reobserve one selected source under the preparation operation."""
    operation.checkpoint()
    try:
        status = path.lstat()
    except OSError as error:
        operation.checkpoint()
        raise SelectedResourceRejected("artifact_rejected") from error
    operation.checkpoint()
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise SelectedResourceRejected("artifact_rejected")
    if any(".." == part for part in path.parts):
        raise SelectedResourceRejected("artifact_rejected")
    try:
        if _has_symlink_ancestry(path, operation):
            raise SelectedResourceRejected("artifact_rejected")
        operation.checkpoint()
        canonical = path.resolve(strict=True)
        operation.checkpoint()
        canonical_status = canonical.lstat()
    except SelectedResourceRejected:
        raise
    except (OSError, RuntimeError) as error:
        operation.checkpoint()
        raise SelectedResourceRejected("artifact_rejected") from error
    operation.checkpoint()
    if stat.S_ISLNK(canonical_status.st_mode) or not stat.S_ISREG(canonical_status.st_mode):
        raise SelectedResourceRejected("artifact_rejected")
    return canonical, file_identity(canonical_status)


def revalidate_selected_batch(batch, operation):
    """Revalidate every selected source immediately before capture."""
    for work in batch:
        selected = getattr(work, "selected", None)
        if selected is None:
            continue
        canonical, identity = _selected_identity(selected.source_path, operation)
        if canonical != selected.source_path or identity != selected.identity:
            raise SelectedResourceRejected("artifact_rejected")
        operation.checkpoint()
    return tuple(batch)


def validate_selected_capture(work, captured_entry):
    """Correlate one captured entry with its selected source evidence."""
    selected = work.selected
    if selected is None:
        return
    if (
        captured_entry.kind != work.candidate.kind if isinstance(work, _ModuleWork)
        else captured_entry.kind != "script"
    ):
        raise SelectedResourceRejected("artifact_rejected")
    expected_name = (
        work.candidate.logical_name if isinstance(work, _ModuleWork)
        else work.entry.final_registered_name
    )
    if (
        captured_entry.logical_name != expected_name
        or captured_entry.validation.source_path != selected.source_path
        or captured_entry.validation.identity != selected.identity
    ):
        raise SelectedResourceRejected("artifact_rejected")


def _capture_batches(works):
    """Pack complete Hook Point groups without repeating source paths."""
    if not works:
        return ()
    if not any(getattr(work, "selected", None) is not None for work in works):
        return tuple(
            tuple(works[start:start + 128])
            for start in range(0, len(works), 128)
        )

    groups = []
    index = 0
    while index < len(works):
        hook_index = works[index].hook_index
        end = index
        while end < len(works) and works[end].hook_index == hook_index:
            end += 1
        group = tuple(works[index:end])
        if len(group) > 128:
            raise SelectedResourceRejected("capacity_exceeded")
        paths = frozenset(_work_source_path(work) for work in group)
        groups.append((group, paths))
        index = end

    batches = []
    current = []
    current_paths = set()
    for group, paths in groups:
        if current and (
            len(current) + len(group) > 128
            or current_paths.intersection(paths)
        ):
            batches.append(tuple(current))
            current = []
            current_paths = set()
        current.extend(group)
        current_paths.update(paths)
    if current:
        batches.append(tuple(current))
    if len(batches) > 8:
        raise SelectedResourceRejected("capacity_exceeded")
    return tuple(batches)


def _work_source_path(work):
    """Return the capture source path for one preparation work item."""
    if isinstance(work, _ModuleWork):
        return work.candidate.source_path
    return work.entry.source_path


def selected_point_work(point, hook_index, operation, budget):
    """Build strict Module and Script work records for one selected point."""
    resources = point.resources
    if resources is None:
        return ()
    module_inventory = build_selected_inventory(
        resources.selection.modules, kind="modules", operation=operation, budget=budget,
    )
    script_inventory = build_selected_inventory(
        resources.selection.scripts,
        kind="scripts",
        script_policy=(resources.script_settings.platform_policy if resources.script_settings else None),
        operation=operation,
        budget=budget,
    )
    physical = {
        (entry.identity.device, entry.identity.inode)
        for entry in module_inventory.entries
    }
    if physical.intersection(
        (entry.identity.device, entry.identity.inode)
        for entry in script_inventory.entries
    ):
        raise SelectedResourceRejected("binding_conflict")
    module_work = tuple(
        _ModuleWork(hook_index, point, entry.selection_root,
                    ModuleCandidate(entry.registered_name, entry.source_path, entry.kind),
                    entry)
        for entry in module_inventory.entries
    )
    script_work = tuple(
        _ScriptWork(hook_index, point,
                    HookScriptEntry(entry.source_path, entry.registered_name, entry.registered_name),
                    entry)
        for entry in script_inventory.entries
    )
    return module_work + script_work


def script_settings(point):
    """Return target-free or legacy Script execution settings."""
    resources = getattr(point, "resources", None)
    if resources is not None and resources.script_settings is not None:
        return resources.script_settings
    return getattr(point, "script", None)


def script_selection_configured(point):
    """Return whether Script configuration exists independently of discovered entries."""
    resources = getattr(point, "resources", None)
    if resources is not None:
        return resources.selection.scripts is not None
    return getattr(point, "script", None) is not None


def build_executable_plan(point, captured):
    """Build one complete executable plan from correlated captured work."""
    from topsailai.hooks.artifact_contracts import ArtifactCaptureRequest
    from topsailai.hooks.hook_point_plan_contracts import (
        CapturedModule, CapturedScript, DefaultScriptHook, HookPointPlan, ModuleSource,
    )
    from topsailai.hooks.module_invocation_protocol import ModuleInvocation
    from topsailai.hooks.result_contracts import HandlerIdentity

    settings = script_settings(point)
    if len(captured) > 128 or (captured and len({item.lease.identity for item in captured}) != 1):
        raise _ExecutablePlanRejected("binding_conflict")
    modules, scripts = [], []
    for item in captured:
        index = item.entry_index
        entry = item.lease.entries[index]
        work = item.work
        if isinstance(work, _ModuleWork):
            request = ArtifactCaptureRequest(
                work.candidate.source_path,
                work.candidate.kind,
                work.candidate.logical_name,
            )
        else:
            request = ArtifactCaptureRequest(
                work.entry.source_path,
                "script",
                work.entry.final_registered_name,
                settings.platform_policy,
            )
        if (entry.index, entry.kind, entry.logical_name, entry.validation.source_path) != (
            index, request.kind, request.logical_name, request.source_path
        ):
            raise _ExecutablePlanRejected("artifact_rejected")
        if isinstance(work, _ModuleWork):
            logical = work.candidate.logical_name
            source = ModuleSource(
                f"{point.hook_name}:{logical}",
                work.candidate.source_path,
                logical,
                work.candidate.kind,
                f"{logical}:main",
                ModuleInvocation(
                    point.module_args,
                    dict(point.module_kwargs),
                    inject_hook_context=point.inject_hook_context,
                ),
            )
            modules.append(
                CapturedModule(
                    HandlerIdentity(f"module-{index}", source.registered_name, "module"),
                    source,
                    item.lease.identity,
                    index,
                    entry.relative_path,
                    item.captured_path,
                    entry.content_sha256,
                    entry.validation.deployment_sha256,
                )
            )
            continue
        scripts.append(
            CapturedScript(
                HandlerIdentity(f"script-{index}", work.entry.final_registered_name, "script"),
                item.lease.identity,
                index,
                work.entry.source_path,
                work.entry.basename,
                entry.relative_path,
                item.captured_path,
                entry.content_sha256,
                entry.validation.deployment_sha256,
            )
        )
    return HookPointPlan(
        point.hook_name,
        tuple(modules),
        DefaultScriptHook(tuple(scripts), script_selection_configured(point)),
        settings.options if settings is not None else HookScriptExecutionOptions(),
        settings.policy if settings is not None else HookScriptExecutionPolicy(),
        ArtifactCapturePolicy(max_entries=max(1, len(captured))),
        platform_policy=(settings.platform_policy if settings is not None else ExecutablePlatformPolicy("posix")),
    )
