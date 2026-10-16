"""Finite direct-entry summary operation ownership. Author: DawsonLin."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.points.context.summary_adapter import (
    DirectSummaryOperation, _CHECKPOINTS, current_summary_operation, summary_operation,
    emit_summary_checkpoint,
)


@pytest.fixture
def calls(monkeypatch):
    """Observe only direct entries after the real adapter validation."""
    observed = []
    for points in _CHECKPOINTS.values():
        for point in points.values():
            def entry(*, operation_id, _name=point.NAME, **classification):
                """Record detached scalar call arguments."""
                observed.append((_name, operation_id, classification))
                return ()
            monkeypatch.setattr(point, point.NAME, entry)
    return observed


def test_validation_does_not_consume_checkpoint(calls):
    """Invalid fields and inactive checkpoints never consume a valid occurrence."""
    operation = DirectSummaryOperation('user2agent')
    with pytest.raises(ValidationError):
        operation.emit('before_summary_generate', secret='forbidden')
    with pytest.raises(ValidationError):
        operation.emit('after_summary_generate')
    with pytest.raises(ValidationError):
        operation.emit('error_summary_apply', error_category='unknown',
                       failed_stage='token_stat_update', partial_apply_possible=True)
    operation.emit('before_summary_generate')
    assert operation.emit('before_summary_generate').already_handled
    assert len(calls) == 1


def test_nested_restoration_and_exception(calls):
    """An inner summary restores the exact outer state even on failure."""
    failure = RuntimeError('business')

    @summary_operation('agent2llm')
    def inner():
        """Consume an independent point then fail."""
        current_summary_operation().emit('before_summary_generate')
        raise failure

    @summary_operation('user2agent')
    def outer():
        """Retain exact custody and deduplication around a nested summary."""
        operation = current_summary_operation()
        operation.emit('before_summary_generate')
        with pytest.raises(RuntimeError) as caught:
            inner()
        assert caught.value is failure
        assert current_summary_operation() is operation
        assert operation.emit('before_summary_generate').already_handled
        return operation.operation.operation_id

    first, second = outer(), outer()
    assert first != second
    assert len(calls) == 4
    assert current_summary_operation() is None


def test_copied_context_thread_and_task_cannot_borrow(calls):
    """Both explicit context copies and inherited task contexts lose foreign custody."""
    @summary_operation('user2agent')
    def business():
        """Probe copied thread context and inherited asynchronous task state."""
        operation = current_summary_operation()
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(context.run, current_summary_operation).result() is None
            with pytest.raises(ValidationError):
                pool.submit(operation.emit, 'before_summary_generate').result()

        async def child():
            """Reject a copied parent operation in a new task."""
            assert current_summary_operation() is None
            with pytest.raises(ValidationError):
                operation.emit('before_summary_generate')

        asyncio.run(child())
        assert current_summary_operation() is operation
    business()
    assert calls == []


@pytest.mark.parametrize('error', [RuntimeError(), KeyboardInterrupt(), asyncio.CancelledError()])
def test_error_observer_never_replaces_business_exception(calls, monkeypatch, error):
    """Any observer failure at an error checkpoint preserves the active exception."""
    point = _CHECKPOINTS['user2agent']['error_summary_generate']

    def fail(**kwargs):
        """Simulate failure of the direct observer boundary."""
        raise error

    monkeypatch.setattr(point, point.NAME, fail)
    primary = ValueError('business')

    @summary_operation('user2agent')
    def business():
        """Use the real error-dispatch guard while a business exception is active."""
        try:
            raise primary
        except ValueError:
            emit_summary_checkpoint('error_summary_generate',
                error_category='unknown', failed_stage='generation_request')
            raise

    with pytest.raises(ValueError) as caught:
        business()
    assert caught.value is primary
    assert current_summary_operation() is None


def test_unbound_and_invalid_layer():
    """No operation lookup constructs runtime resources; invalid scopes reject."""
    assert emit_summary_checkpoint('before_summary_generate') is None
    with pytest.raises(ValidationError):
        summary_operation('other')


def test_saved_context_expires_after_summary(calls):
    """A copied same-thread context cannot resurrect a completed summary."""
    @summary_operation('user2agent')
    def business():
        """Capture the active context without extending its lifetime."""
        return copy_context(), current_summary_operation()

    context, operation = business()
    assert context.run(current_summary_operation) is None
    with pytest.raises(ValidationError):
        context.run(operation.emit, 'before_summary_generate')
    assert calls == []


def test_failed_entry_is_consumed_before_reentry(calls, monkeypatch):
    """A failed direct entry cannot be retried within the same operation."""
    operation = DirectSummaryOperation('user2agent')
    point = _CHECKPOINTS['user2agent']['before_summary_generate']
    failure = RuntimeError('observer')

    def fail(**kwargs):
        """Reenter before raising to verify pre-dispatch checkpoint marking."""
        assert operation.emit('before_summary_generate').already_handled
        raise failure

    monkeypatch.setattr(point, point.NAME, fail)
    with pytest.raises(RuntimeError) as caught:
        operation.emit('before_summary_generate')
    assert caught.value is failure
    assert operation.emit('before_summary_generate').already_handled
    assert calls == []


def test_parallel_operations_have_independent_custody(calls):
    """Two simultaneous summaries never share checkpoint state or correlation."""
    from threading import Barrier
    ready = Barrier(2)

    @summary_operation('user2agent')
    def business():
        """Overlap operations and consume the same logical checkpoint once each."""
        operation = current_summary_operation()
        ready.wait(timeout=5)
        operation.emit('before_summary_generate')
        assert operation.emit('before_summary_generate').already_handled
        return operation.operation.operation_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(business) for _ in range(2)]
        identities = [future.result() for future in futures]
    assert len(set(identities)) == 2
    assert len(calls) == 2
    assert current_summary_operation() is None


@pytest.mark.parametrize('layer', ['user2agent', 'agent2llm'])
@pytest.mark.parametrize('checkpoint', ['before_summary_generate', 'after_summary_apply',
                                      'error_summary_generate', 'error_summary_apply'])
@pytest.mark.parametrize('failure_kind', ['ordinary', 'base', 'control'])
def test_emitter_guard_preserves_checkpoint_precedence(monkeypatch, layer, checkpoint, failure_kind):
    """Only non-error checkpoints propagate observer control signals unchanged."""
    from concurrent.futures import CancelledError

    error = {'ordinary': RuntimeError('private'), 'base': KeyboardInterrupt(),
             'control': CancelledError()}[failure_kind]
    selected = _CHECKPOINTS[layer][checkpoint]

    def fail(**kwargs):
        """Raise an exact observer error after admission and payload validation."""
        raise error

    monkeypatch.setattr(selected, selected.NAME, fail)
    classification = {}
    if checkpoint.startswith('error_'):
        classification = {'error_category': 'unknown', 'failed_stage':
                          'generation_request' if checkpoint.endswith('generate') else 'application_unknown'}
        if checkpoint.endswith('apply'):
            classification['partial_apply_possible'] = True

    @summary_operation(layer)
    def business():
        """Verify guard disposition and once-only consumption in the real scope."""
        if not checkpoint.startswith('error_') and failure_kind != 'ordinary':
            with pytest.raises(type(error)) as caught:
                emit_summary_checkpoint(checkpoint, **classification)
            assert caught.value is error
        else:
            assert emit_summary_checkpoint(checkpoint, **classification) is None
        assert emit_summary_checkpoint(checkpoint, **classification).already_handled

    business()
    assert current_summary_operation() is None


def test_emitter_returns_exact_direct_result(calls, monkeypatch):
    """The extracted emitter never wraps or replaces a normal dispatch result."""
    selected = _CHECKPOINTS['user2agent']['before_summary_generate']
    result = object()
    monkeypatch.setattr(selected, selected.NAME, lambda **kwargs: result)

    @summary_operation('user2agent')
    def business():
        """Retain the exact value from the selected direct entry."""
        assert emit_summary_checkpoint('before_summary_generate') is result

    business()
