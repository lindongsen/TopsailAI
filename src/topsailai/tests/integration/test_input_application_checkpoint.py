"""Integration evidence for the application-owned input checkpoint."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from topsailai.hooks import (
    ConfiguredHookPoint,
    ConfiguredHooks,
    ConfiguredTrustPolicy,
    HookSettings,
)
from topsailai.hooks.application_access import get_hook_executor
from topsailai.hooks.configured_contracts import SummaryPreparationRequest
from topsailai.hooks.hook_point_catalog import HookPointCatalog
from topsailai.hooks.points.workspace.before_input_message import POINT
from topsailai.workspace import input_tool
from topsailai.workspace.hooks_application import HooksApplication
from tests.integration.test_hooks_application_lifecycle import (
    _runtime_authority,
    _source_assertion,
)


@pytest.fixture
def prepared_application(tmp_path):
    """Create one real prepared application and close it after the test."""
    source_root = tmp_path / "input" / "sources"
    source_root.mkdir(mode=0o700, parents=True)
    folder = source_root / POINT.name
    folder.mkdir(mode=0o700)
    source = folder / "worker.py"
    source.write_text(
        "def main(*, hook_context):\n"
        "    return {\"operation_id\": hook_context[\"operation_id\"],\n"
        "            \"payload\": dict(hook_context[\"payload\"])}\n",
        encoding="utf-8",
    )
    authority = _runtime_authority()
    configuration = ConfiguredHooks(
        (ConfiguredHookPoint(
            POINT.name,
            POINT.definition,
            module_folder=folder,
            inject_hook_context=True,
        ),),
        HookSettings(),
    )
    request = SummaryPreparationRequest(
        configuration,
        HookPointCatalog((POINT,)),
        frozenset(),
    )
    trust = ConfiguredTrustPolicy(
        (source_root,),
        closure_assertions=(_source_assertion(source, "worker", authority),),
        python_runtime=authority,
    )
    application = HooksApplication(
        request=request,
        trust_policy=trust,
        temp_root=str(tmp_path / "input" / "runtime"),
    )
    yield application
    if not application.close_result.fully_closed:
        application.close()


def test_input_uses_bound_application_before_first_read(prepared_application, monkeypatch):
    """The real Module and terminal Hook complete before input acquisition."""
    application = prepared_application
    events = []
    reports = []
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)

    def read(*args):
        events.append("read")
        return "message"

    monkeypatch.setattr(input_tool, "_input", read)
    original_dispatch = application.executor.dispatch

    def dispatch(point, *, payload, operation, **kwargs):
        """Record settled real Hook results before the reader runs."""
        report = original_dispatch(point, payload=payload, operation=operation, **kwargs)
        reports.append((operation, payload, report))
        handlers = report.unified_result.handlers
        assert [item.handler.kind for item in handlers] == ["module", "default_script_hook"]
        assert len(handlers) == 2
        assert all(item.status == "success" for item in handlers)
        assert all(item.cleanup.state == "safe" for item in handlers)
        assert handlers[0].returned.value == {
            "operation_id": operation.operation_id,
            "payload": {"multiline": False},
        }
        events.append("hook")
        return report

    monkeypatch.setattr(application.executor, "dispatch", dispatch)
    with application:
        assert input_tool.input_message() == "message"
    assert events == ["hook", "read"]
    assert len(reports) == 1
    operation, payload, report = reports[0]
    assert operation.operation_id == report.unified_result.handlers[0].returned.value["operation_id"]
    assert payload == {"multiline": False}
    assert report.rejection_reason is None


def test_real_application_retries_without_redispatch_and_remains_usable(
    prepared_application, monkeypatch
):
    """One real checkpoint precedes all internal reads and later calls still work."""
    application = prepared_application
    events = []
    reports = []
    values = iter(("", "message", "after-retry"))
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)

    def read(*args):
        """Record every reader call and supply an empty retry before text."""
        events.append("read")
        return next(values)

    monkeypatch.setattr(input_tool, "_input", read)
    original_dispatch = application.executor.dispatch

    def dispatch(point, *, payload, operation, **kwargs):
        """Require the real prepared stages to settle before the first read."""
        assert events == [] or all(event == "read" for event in events)
        report = original_dispatch(point, payload=payload, operation=operation, **kwargs)
        reports.append(report)
        handlers = report.unified_result.handlers
        assert [item.handler.kind for item in handlers] == [
            "module", "default_script_hook",
        ]
        assert len(handlers) == 2
        assert [item.status for item in handlers] == ["success", "success"]
        assert all(item.cleanup.state == "safe" for item in handlers)
        assert handlers[0].returned.value == {
            "operation_id": operation.operation_id,
            "payload": {"multiline": False},
        }
        return report

    monkeypatch.setattr(application.executor, "dispatch", dispatch)
    with application:
        assert input_tool.input_message() == "message"
        assert len(reports) == 1
        assert events == ["read", "read"]
        assert input_tool.input_message() == "after-retry"
        assert len(reports) == 2
        assert all(
            [item.handler.kind for item in report.unified_result.handlers]
            == ["module", "default_script_hook"]
            for report in reports
        )
        assert not application.access._admission_stopped


def test_input_calls_share_owner_and_receive_fresh_operations(prepared_application, monkeypatch):
    """Separate complete acquisitions use one owner and distinct operation IDs."""
    application = prepared_application
    operations = []
    reports = []
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)
    monkeypatch.setattr(input_tool, "_input", lambda *args: "message")
    original_dispatch = application.executor.dispatch

    def dispatch(point, *, payload, operation, **kwargs):
        """Capture correlation while preserving real execution."""
        operations.append(operation.operation_id)
        report = original_dispatch(point, payload=payload, operation=operation, **kwargs)
        reports.append(report)
        return report

    monkeypatch.setattr(application.executor, "dispatch", dispatch)
    with application:
        assert input_tool.input_message() == "message"
        assert input_tool.input_message() == "message"
        assert len(reports) == 2
        assert all(report.rejection_reason is None for report in reports)
        assert all(
            len(report.unified_result.handlers) == 2
            and [item.handler.kind for item in report.unified_result.handlers]
            == ["module", "default_script_hook"]
            and all(item.status == "success" for item in report.unified_result.handlers)
            for report in reports
        )
        assert len(operations) == 2
        assert len(set(operations)) == 2
        assert not application.access._admission_stopped
    assert application.close_result.fully_closed


def test_nested_application_binding_is_restored_after_input(
    prepared_application, monkeypatch, tmp_path
):
    """Nested application binding restores the outer owner after input returns."""
    outer = prepared_application
    inner_root = tmp_path / "inner"
    source_root = inner_root / "sources"
    source_root.mkdir(mode=0o700, parents=True)
    folder = source_root / POINT.name
    folder.mkdir(mode=0o700)
    source = folder / "worker.py"
    source.write_text(
        "def main(*, hook_context):\n"
        "    return {\"operation_id\": hook_context[\"operation_id\"]}\n",
        encoding="utf-8",
    )
    authority = _runtime_authority()
    request = SummaryPreparationRequest(
        ConfiguredHooks((ConfiguredHookPoint(
            POINT.name, POINT.definition, module_folder=folder, inject_hook_context=True,
        ),), HookSettings()),
        HookPointCatalog((POINT,)),
        frozenset(),
    )
    inner = HooksApplication(
        request=request,
        trust_policy=ConfiguredTrustPolicy(
            (source_root,), closure_assertions=(_source_assertion(source, "worker", authority),),
            python_runtime=authority,
        ),
        temp_root=str(inner_root / "runtime"),
    )
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)
    monkeypatch.setattr(input_tool, "_input", lambda *args: "message")
    from topsailai.hooks.application_access import HookApplicationAccess, bind_hook_application

    try:
        with outer:
            with bind_hook_application(HookApplicationAccess(inner.executor)):
                assert input_tool.input_message() == "message"
            assert get_hook_executor()._binding.application is outer.access
    finally:
        assert inner.close().fully_closed


def test_closed_bound_application_does_not_forward_but_input_continues(
    prepared_application, monkeypatch
):
    """A stopped application reports closure while ordinary input continues."""
    application = prepared_application
    reader = Mock(return_value="message")
    forwarded = Mock()
    monkeypatch.setattr(input_tool, "_append_input_history_jsonl", Mock())
    monkeypatch.setattr(input_tool, "_input", reader)
    monkeypatch.setattr(input_tool.env_tool, "is_chat_multi_line", lambda: False)
    monkeypatch.setattr(application.executor, "dispatch", forwarded)
    application.access.stop_admission()
    with application:
        assert input_tool.input_message() == "message"
    forwarded.assert_not_called()
    reader.assert_called_once()
    assert get_hook_executor()._binding is None
