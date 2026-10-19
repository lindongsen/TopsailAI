"""Preserved real accounting parity after control-route retirement."""
from types import SimpleNamespace
import pytest
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.first_byte_timeout import FirstByteTimeoutMixin
from topsailai.ai_base.llm_control import first_byte_timeout as timeout_module
from topsailai.ai_base.llm_control.request_tracking import record_llm_request_outcome, iter_stream_for_request_timing
from topsailai.ai_base.llm_control.response_ownership import response_ownership_scope
from topsailai.context.llm_request_stat import LLMRequestStat, RequestTimingTicket
from topsailai.utils import thread_local_tool
from topsailai.utils.thread_local_tool import get_agent_object

class Host(FirstByteTimeoutMixin):
    """Provide deterministic request/iterator and bookkeeping seams."""

    def __init__(self, response):
        """Retain a provider operation and exact timing observations."""
        self.response = response
        self.calls = []
        self.warnings = []
        self.finished = []

    def _build_first_byte_request_parameters(self, messages, **kwargs):
        """Detach supplied request data for the provider worker."""
        return (messages, kwargs)

    def _create_first_byte_response(self, params):
        """Invoke the test provider without replacing control coordination."""
        self.calls.append(params)
        return self.response()

    def _start_first_byte_request(self):
        """Return one distinct timing identity."""
        return object()

    def _finish_first_byte_request(self, ticket):
        """Record exact finishing without sleep or process-global state."""
        self.finished.append(ticket)

    def _publish_first_byte_request_ticket(self, ticket):
        """Retain the accepted ticket."""
        self.ticket = ticket

    def _complete_first_byte_request(self, ticket, *, stream):
        """Match production pause-versus-finish accounting."""
        if not stream:
            self.finished.append(ticket)

    def _get_llm_request_timing_ticket(self):
        """Expose accepted ticket for the first fetch."""
        return getattr(self, "ticket", None)

    def _resume_llm_request(self, ticket):
        """Accept an exact timing resume."""

    def _make_first_byte_timeout_error(self, timeout):
        """Create a recognizable domain timeout."""
        return TimeoutError("controlled deadline")

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Record warning cardinality."""
        self.warnings.append((elapsed, timeout))


class AccountingHost(Host):
    """Compose genuine production ticket methods with an isolated provider."""
    _start_first_byte_request = LLMModel._start_first_byte_request
    _publish_first_byte_request_ticket = LLMModel._publish_first_byte_request_ticket
    _pause_first_byte_request = LLMModel._pause_first_byte_request
    _finish_first_byte_request = LLMModel._finish_first_byte_request
    _complete_first_byte_request = LLMModel._complete_first_byte_request
    _start_llm_request = LLMModel._start_llm_request
    _finish_llm_request = LLMModel._finish_llm_request
    _get_llm_request_stat = LLMModel._get_llm_request_stat
    _get_llm_request_timing_ticket = LLMModel._get_llm_request_timing_ticket
    _resume_llm_request = LLMModel._resume_llm_request
    _pause_llm_request = LLMModel._pause_llm_request
    _record_llm_request_success = LLMModel._record_llm_request_success
    _record_llm_request_failure = LLMModel._record_llm_request_failure
    _record_llm_request_stat = LLMModel._record_llm_request_stat

    def __init__(self, provider):
        """Use an explicit clock and retain ticket identity for assertions."""
        super().__init__(provider)
        self.now = 1.0
        self.llm_request_stat = LLMRequestStat(clock=lambda: self.now)
        self.exact_ticket = None

    @record_llm_request_outcome
    def invoke(self, stream, timeout, raising=False):
        """Match production streaming timing and outcome composition."""
        result = self._create_with_first_byte_timeout(
            [], stream=stream, first_byte_timeout=timeout, raise_on_timeout=raising,
        )
        self.exact_ticket = self._get_llm_request_timing_ticket()
        if not stream:
            return result
        iterator = self.iter_stream_with_first_byte_timeout(
            result[0], timeout, raise_on_timeout=raising,
        )
        iterator = iter_stream_for_request_timing(
            iterator, self.exact_ticket, resume=self._resume_llm_request,
            pause=self._pause_llm_request,
            first_operation=timeout > 0 or thread_local_tool.get_agent_object() is not None,
        )
        values = list(iterator)
        self._finish_llm_request(self.exact_ticket)
        return values


@pytest.mark.parametrize("timeout", [-1, 0, 1])
@pytest.mark.parametrize("stream,phase", [(False, "value"), (False, "create_error"),
                                         (True, "value"), (True, "eof"),
                                         (True, "fetch_error")])
def test_real_accounting_agent_parity(monkeypatch, timeout, stream, phase):
    """Creation/fetch/EOF each produce one exact outcome and duration sample."""
    snapshots = []
    error = LookupError("exact provider failure")
    for routed in (False, True):
        def records():
            """Keep decoded metadata and payload inside the timing boundary."""
            if phase == "fetch_error":
                raise error
            if phase != "eof":
                yield ""
                yield "body"

        def provider():
            """Fail or publish through the unchanged request adapter."""
            if phase == "create_error":
                raise error
            return records() if stream else "body"

        host = AccountingHost(provider)
        monkeypatch.setattr(thread_local_tool, "get_agent_object",
                            lambda: SimpleNamespace(_check_hard_interrupt=lambda: None) if routed else None)
        monkeypatch.setattr(timeout_module, "get_agent_object", thread_local_tool.get_agent_object)
        with response_ownership_scope():
            if phase.endswith("error"):
                with pytest.raises(LookupError) as caught:
                    host.invoke(stream, timeout)
                assert caught.value is error
            else:
                assert host.invoke(stream, timeout) == ([] if phase == "eof" else ["", "body"] if stream else "body")
                assert isinstance(host.exact_ticket, RequestTimingTicket)
        snapshot = host.llm_request_stat.get_request_stat_info()
        assert snapshot["total_requests"] == 1
        assert snapshot["request_successes"] == (not phase.endswith("error"))
        assert snapshot["request_failures"] == phase.endswith("error")
        assert snapshot["request_duration_count"] == 1
        snapshots.append(snapshot)
    assert snapshots[0] == snapshots[1]
