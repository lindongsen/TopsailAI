"""Tests for provider-neutral first-byte timeout orchestration."""

import threading
import time
import unittest
from unittest.mock import MagicMock

from topsailai.ai_base.llm_control.first_byte_timeout import (
    FirstByteTimeoutMixin,
    iter_with_first_byte_timeout,
)


class _BlockingIterator:
    """Block first-item retrieval until timeout cleanup closes the iterator."""

    def __init__(self, close_error=None):
        """Initialize synchronization and optional close failure."""
        self.started = threading.Event()
        self.released = threading.Event()
        self.closed = False
        self.close_error = close_error

    def __iter__(self):
        """Return this iterator."""
        return self

    def __next__(self):
        """Wait for close before ending the stream."""
        self.started.set()
        self.released.wait(1)
        raise StopIteration

    def close(self):
        """Record closure, release the worker, and optionally fail."""
        self.closed = True
        self.released.set()
        if self.close_error is not None:
            raise self.close_error


class _ThreadRecordingIterator:
    """Record which threads retrieve the first and subsequent values."""

    def __init__(self):
        """Initialize two values and an empty thread record."""
        self.values = iter(("first", "second"))
        self.thread_ids = []

    def __iter__(self):
        """Return this iterator."""
        return self

    def __next__(self):
        """Record the caller thread and return the next value."""
        self.thread_ids.append(threading.get_ident())
        return next(self.values)


class TestIterWithFirstByteTimeout(unittest.TestCase):
    """Verify the standalone helper without provider dependencies."""

    def setUp(self):
        """Create injected timeout callbacks."""
        self.on_timeout = MagicMock()
        self.timeout_error = TimeoutError("first item timed out")
        self.make_timeout_error = MagicMock(return_value=self.timeout_error)

    def _collect(self, stream, timeout=1, **kwargs):
        """Collect helper output with the shared callbacks."""
        return list(
            iter_with_first_byte_timeout(
                stream,
                timeout,
                on_timeout=self.on_timeout,
                make_timeout_error=self.make_timeout_error,
                **kwargs,
            )
        )

    def test_disabled_timeout_passes_through_stream(self):
        """A non-positive timeout bypasses first-item orchestration."""
        self.assertEqual(self._collect(iter((1, 2)), timeout=0), [1, 2])
        self.on_timeout.assert_not_called()
        self.make_timeout_error.assert_not_called()

    def test_fast_first_value_and_empty_iterator(self):
        """Fast and empty iterators complete without timeout callbacks."""
        self.assertEqual(self._collect(iter(("value",))), ["value"])
        self.assertEqual(self._collect(iter(())), [])
        self.on_timeout.assert_not_called()

    def test_source_exception_is_propagated_by_identity(self):
        """The first-item source exception reaches the caller unchanged."""
        source_error = RuntimeError("source failed")

        def failing_iterator():
            """Raise the controlled source error before yielding."""
            raise source_error
            yield

        with self.assertRaises(RuntimeError) as caught:
            self._collect(failing_iterator())

        self.assertIs(caught.exception, source_error)
        self.on_timeout.assert_not_called()

    def test_timeout_warns_closes_and_stops_without_raise(self):
        """A monitoring timeout closes the stream and ends iteration."""
        stream = _BlockingIterator()

        self.assertEqual(self._collect(stream, timeout=0.01), [])

        self.assertTrue(stream.started.is_set())
        self.assertTrue(stream.closed)
        self.assertTrue(stream.released.wait(1))
        self.on_timeout.assert_called_once()
        self.assertGreaterEqual(self.on_timeout.call_args.args[0], 0.01)
        self.assertEqual(self.on_timeout.call_args.args[1], 0.01)
        self.make_timeout_error.assert_not_called()

    def test_timeout_raises_injected_error(self):
        """Raising mode uses the provider-supplied exception factory."""
        stream = _BlockingIterator()

        with self.assertRaises(TimeoutError) as caught:
            self._collect(stream, timeout=0.01, raise_on_timeout=True)

        self.assertIs(caught.exception, self.timeout_error)
        self.make_timeout_error.assert_called_once_with(0.01)
        self.on_timeout.assert_called_once()

    def test_create_timeout_suppresses_duplicate_warning(self):
        """An earlier create timeout suppresses only the duplicate warning."""
        stream = _BlockingIterator()

        self.assertEqual(
            self._collect(stream, timeout=0.01, create_timed_out=True),
            [],
        )

        self.assertTrue(stream.closed)
        self.on_timeout.assert_not_called()

    def test_close_failure_does_not_replace_timeout_result(self):
        """A stream close failure is swallowed after releasing the worker."""
        stream = _BlockingIterator(RuntimeError("close failed"))

        self.assertEqual(self._collect(stream, timeout=0.01), [])

        self.assertTrue(stream.closed)
        self.on_timeout.assert_called_once()

    def test_only_first_item_is_retrieved_in_timeout_worker(self):
        """Subsequent items are consumed normally in the caller thread."""
        stream = _ThreadRecordingIterator()
        caller_thread = threading.get_ident()

        self.assertEqual(self._collect(stream), ["first", "second"])

        self.assertNotEqual(stream.thread_ids[0], caller_thread)
        self.assertEqual(stream.thread_ids[1:], [caller_thread, caller_thread])
        self.on_timeout.assert_not_called()



class _FirstByteHost(FirstByteTimeoutMixin):
    """Provide controlled adapters for standalone mixin tests."""

    def __init__(self, result=None, error=None, delay=0):
        """Initialize provider behavior and adapter observations."""
        self.result = result
        self.error = error
        self.delay = delay
        self.events = []
        self.warning = MagicMock()
        self.timeout_error = TimeoutError("create timed out")

    def _build_first_byte_request_parameters(self, messages, **kwargs):
        """Return provider-neutral test parameters."""
        return {"messages": messages, **kwargs}

    def _create_first_byte_response(self, params):
        """Return or raise the configured provider result."""
        self.events.append(("create", params))
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result

    def _start_first_byte_request(self):
        """Create a deterministic timing ticket."""
        self.events.append("start")
        return "ticket"

    def _pause_first_byte_request(self, ticket):
        """Record stream timing pause."""
        self.events.append(("pause", ticket))

    def _finish_first_byte_request(self, ticket):
        """Record request timing finish."""
        self.events.append(("finish", ticket))

    def _publish_first_byte_request_ticket(self, ticket):
        """Record publication in the caller thread."""
        self.events.append(("publish", ticket, threading.get_ident()))

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Record timeout reporting."""
        self.warning(elapsed, timeout)

    def _make_first_byte_timeout_error(self, timeout):
        """Return the controlled timeout error."""
        return self.timeout_error


class TestFirstByteTimeoutMixin(unittest.TestCase):
    """Verify create orchestration through provider-neutral adapters."""

    def test_disabled_stream_preserves_result_shape_and_accounting(self):
        """Disabled monitoring returns the stream tuple and pauses once."""
        response = object()
        host = _FirstByteHost(result=response)

        result = host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=0)

        self.assertEqual(result, (response, False))
        self.assertIn(("pause", "ticket"), host.events)
        self.assertNotIn(("finish", "ticket"), host.events)
        host.warning.assert_not_called()

    def test_monitored_create_returns_result_and_finishes_once(self):
        """A fast non-stream create returns its response and completes timing."""
        response = object()
        host = _FirstByteHost(result=response)

        result = host._create_with_first_byte_timeout([], first_byte_timeout=1)

        self.assertIs(result, response)
        self.assertEqual(host.events.count(("finish", "ticket")), 1)
        self.assertEqual(len([event for event in host.events if event == "start"]), 1)

    def test_warning_timeout_waits_for_real_stream_result(self):
        """Warning mode waits for create and marks the stream as timed out."""
        response = object()
        host = _FirstByteHost(result=response, delay=0.03)

        result = host._create_with_first_byte_timeout(
            [], stream=True, first_byte_timeout=0.01
        )

        self.assertEqual(result, (response, True))
        host.warning.assert_called_once()
        self.assertEqual(host.events.count(("pause", "ticket")), 1)

    def test_raising_timeout_uses_injected_exception(self):
        """Raising mode propagates the exact injected timeout exception."""
        host = _FirstByteHost(result=object(), delay=0.03)

        with self.assertRaises(TimeoutError) as caught:
            host._create_with_first_byte_timeout(
                [], first_byte_timeout=0.01, raise_on_timeout=True
            )

        self.assertIs(caught.exception, host.timeout_error)
        host.warning.assert_called_once()

    def test_provider_exception_is_propagated_by_identity(self):
        """Provider failures retain their original exception identity."""
        error = RuntimeError("provider failed")
        host = _FirstByteHost(error=error)

        with self.assertRaises(RuntimeError) as caught:
            host._create_with_first_byte_timeout([], first_byte_timeout=1)

        self.assertIs(caught.exception, error)
        self.assertEqual(host.events.count(("finish", "ticket")), 1)

if __name__ == "__main__":
    unittest.main()
