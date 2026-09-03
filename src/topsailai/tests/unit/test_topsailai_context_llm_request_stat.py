"""Unit tests for instance-scoped LLM request statistics."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.llm_base import LLMModel
from topsailai.context import llm_request_stat as request_stat_module
from topsailai.context.llm_request_stat import LLMRequestStat


class MutableClock:
    """Provide a controllable monotonic timestamp for rolling-window tests."""

    def __init__(self, value=0.0):
        """Initialize the clock at ``value`` seconds."""
        self.value = value

    def __call__(self):
        """Return the current test timestamp."""
        return self.value


EMPTY_DURATION_METRICS = {
    "request_duration_count": 0,
    "request_duration_min_sec": None,
    "request_duration_avg_sec": None,
    "request_duration_max_sec": None,
    "request_duration_p95_sec": None,
}


def _make_request_model(create_result=None, create_error=None):
    """Build the minimum model required to exercise the provider boundary."""
    model = LLMModel.__new__(LLMModel)
    model.build_parameters_for_chat = MagicMock(return_value={"stream": False})
    model.llm_request_stat = LLMRequestStat()
    model.tokenStat = MagicMock()
    model.models = []
    model.model = MagicMock()
    if create_error is not None:
        model.model.create.side_effect = create_error
    else:
        model.model.create.return_value = create_result
    return model


def test_record_request_reports_total_and_rolling_minute():
    """Each request should increment both counters while inside the window."""
    clock = MutableClock(10.0)
    stat = LLMRequestStat(clock=clock)

    assert stat.record_request() == {
        "total_requests": 1,
        "requests_per_minute": 1,
        "request_successes": 0,
        "request_failures": 0,
        "response_content_errors": 0,
        **EMPTY_DURATION_METRICS,
    }
    clock.value = 69.999
    assert stat.record_request() == {
        "total_requests": 2,
        "requests_per_minute": 2,
        "request_successes": 0,
        "request_failures": 0,
        "response_content_errors": 0,
        **EMPTY_DURATION_METRICS,
    }


def test_requests_at_sixty_seconds_expire_only_from_rpm():
    """The rolling count excludes requests exactly 60 seconds old."""
    clock = MutableClock(0.0)
    stat = LLMRequestStat(clock=clock)
    stat.record_request()

    clock.value = 60.0

    assert stat.get_request_stat_info() == {
        "total_requests": 1,
        "requests_per_minute": 0,
        "request_successes": 0,
        "request_failures": 0,
        "response_content_errors": 0,
        **EMPTY_DURATION_METRICS,
    }


def test_concurrent_recording_loses_no_requests():
    """Concurrent callers should update the shared counters atomically."""
    stat = LLMRequestStat(clock=lambda: 1.0)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: stat.record_request(), range(200)))

    assert stat.get_request_stat_info() == {
        "total_requests": 200,
        "requests_per_minute": 200,
        "request_successes": 0,
        "request_failures": 0,
        "response_content_errors": 0,
        **EMPTY_DURATION_METRICS,
    }


def test_completed_requests_split_into_success_and_failure():
    """Each completed request should increment exactly one outcome counter."""
    stat = LLMRequestStat(clock=lambda: 1.0)
    stat.record_request()
    stat.record_request()

    stat.record_request_success()
    snapshot = stat.record_request_failure()

    assert snapshot == {
        "total_requests": 2,
        "requests_per_minute": 2,
        "request_successes": 1,
        "request_failures": 1,
        "response_content_errors": 0,
        **EMPTY_DURATION_METRICS,
    }
    assert snapshot["request_successes"] + snapshot["request_failures"] == 2


def test_response_content_error_overlaps_success():
    """A successful LLM response may independently produce a tool content error."""
    stat = LLMRequestStat(clock=lambda: 1.0)
    stat.record_request()
    stat.record_request_success()

    snapshot = stat.record_response_content_error()

    assert snapshot == {
        "total_requests": 1,
        "requests_per_minute": 1,
        "request_successes": 1,
        "request_failures": 0,
        "response_content_errors": 1,
        **EMPTY_DURATION_METRICS,
    }


def test_concurrent_request_outcomes_lose_no_updates():
    """Concurrent success and failure updates should remain atomic."""
    stat = LLMRequestStat(clock=lambda: 1.0)
    for _ in range(200):
        stat.record_request()

    outcomes = [True] * 120 + [False] * 80
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(
            lambda success: (
                stat.record_request_success()
                if success
                else stat.record_request_failure()
            ),
            outcomes,
        ))

    snapshot = stat.get_request_stat_info()
    assert snapshot["request_successes"] == 120
    assert snapshot["request_failures"] == 80


def test_request_durations_report_count_min_avg_max_and_p95():
    """Completed timing tickets should produce deterministic duration metrics."""
    clock = MutableClock(10.0)
    stat = LLMRequestStat(clock=clock)

    for duration in [1.0, 2.0, 3.0, 4.0, 5.0]:
        ticket = stat.start_request()
        stat.finish_request(ticket, timestamp=clock.value + duration)

    snapshot = stat.get_request_stat_info()
    assert snapshot["request_duration_count"] == 5
    assert snapshot["request_duration_min_sec"] == 1.0
    assert snapshot["request_duration_avg_sec"] == 3.0
    assert snapshot["request_duration_max_sec"] == 5.0
    assert snapshot["request_duration_p95_sec"] == 4.8


@pytest.mark.parametrize(
    ("durations", "expected_p95"),
    [
        ([1.0, 2.0, 3.0, 4.0, 5.0], 4.8),
        ([1.0, 2.0, 3.0, 4.0], 3.85),
    ],
)
def test_request_duration_p95_uses_linear_interpolation(
    durations, expected_p95
):
    """Odd and even sample counts should use the documented P95 formula."""
    stat = LLMRequestStat(clock=lambda: 0.0)

    for duration in durations:
        stat.finish_request(stat.start_request(), timestamp=duration)

    assert stat.get_request_stat_info()["request_duration_p95_sec"] == expected_p95


def test_request_timing_ticket_finishes_only_once():
    """Repeated cleanup paths must not record one attempt more than once."""
    stat = LLMRequestStat(clock=lambda: 0.0)
    ticket = stat.start_request()

    stat.finish_request(ticket, timestamp=1.0)
    snapshot = stat.finish_request(ticket, timestamp=9.0)

    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 1.0



def test_request_timing_ticket_excludes_paused_non_io_time():
    """Paused intervals such as local stream setup must not affect duration."""
    clock = MutableClock(10.0)
    stat = LLMRequestStat(clock=clock)
    ticket = stat.start_request()

    stat.pause_request(ticket)
    clock.value = 30.0
    stat.resume_request(ticket)
    stat.finish_request(ticket, timestamp=32.0)

    snapshot = stat.get_request_stat_info(timestamp=32.0)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 2.0


class _ClockedChunks:
    """Advance a test clock only while the provider iterator is executing."""

    def __init__(self, clock):
        """Initialize two response chunks and a terminal provider read."""
        self.clock = clock
        self._chunks = iter(["first", "second"])

    def __iter__(self):
        """Return this object as its own iterator."""
        return self

    def __next__(self):
        """Charge two seconds to each provider iterator operation."""
        self.clock.value += 2.0
        return next(self._chunks)


def test_stream_duration_excludes_local_chunk_processing_time():
    """Only create and provider iterator operations contribute to duration."""
    clock = MutableClock(0.0)
    model = LLMModel.__new__(LLMModel)
    model.llm_request_stat = LLMRequestStat(clock=clock)
    ticket = model._start_llm_request()

    clock.value = 1.0
    model._pause_llm_request(ticket)
    for _ in model._iter_stream_for_request_timing(_ClockedChunks(clock), ticket):
        clock.value += 10.0
    model._finish_llm_request(ticket)

    snapshot = model.llm_request_stat.get_request_stat_info()
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 7.0

def test_concurrent_request_tickets_remain_correctly_paired():
    """Concurrent completions should retain each request's own start time."""
    stat = LLMRequestStat(clock=lambda: 10.0)
    tickets = [stat.start_request() for _ in range(100)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda pair: stat.finish_request(pair[0], timestamp=pair[1]),
                zip(tickets, [11.0 + index for index in range(100)]),
            )
        )

    snapshot = stat.get_request_stat_info(timestamp=10.0)
    assert snapshot["request_duration_count"] == 100
    assert snapshot["request_duration_min_sec"] == 1.0
    assert snapshot["request_duration_avg_sec"] == 50.5
    assert snapshot["request_duration_max_sec"] == 100.0
    assert snapshot["request_duration_p95_sec"] == 95.05


def test_models_create_independent_request_trackers(monkeypatch):
    """Direct model contexts must not share request statistics."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    first = LLMModel()
    second = LLMModel()
    try:
        assert first.llm_request_stat is not second.llm_request_stat
        first.llm_request_stat.record_request()
        assert first.llm_request_stat.get_request_stat_info()["total_requests"] == 1
        assert second.llm_request_stat.get_request_stat_info()["total_requests"] == 0
    finally:
        first.close()
        second.close()


def test_print_request_stat_uses_supplied_snapshot(monkeypatch):
    """Printing a snapshot should expose request and duration metric names."""
    print_info = MagicMock()
    monkeypatch.setattr(request_stat_module, "print_info", print_info)
    stat = LLMRequestStat()
    snapshot = {
        "total_requests": 7,
        "requests_per_minute": 3,
        "request_duration_avg_sec": 2.5,
        "request_duration_p95_sec": 4.75,
    }

    stat.print_request_stat(snapshot)

    output = print_info.call_args.args[0]
    assert "LLMRequestStat" in output
    for name, value in snapshot.items():
        assert f"'{name}': {value}" in output


@pytest.mark.parametrize("stream", [False, True])
def test_timeout_disabled_provider_attempt_is_counted_once(stream):
    """Direct provider calls should count once for streaming and regular modes."""
    response = object()
    model = _make_request_model(create_result=response)

    result = model._create_with_first_byte_timeout(
        [{"role": "user", "content": "hello"}],
        stream=stream,
        first_byte_timeout=0,
    )

    snapshot = model.llm_request_stat.get_request_stat_info()
    assert snapshot["total_requests"] == 1
    assert snapshot["request_duration_count"] == (0 if stream else 1)
    model.chat_model.create.assert_called_once()
    assert result == (response, False) if stream else result is response


def test_timeout_monitored_provider_attempt_is_counted_once():
    """The worker-thread provider branch should count exactly one attempt."""
    response = object()
    model = _make_request_model(create_result=response)

    result = model._create_with_first_byte_timeout(
        [{"role": "user", "content": "hello"}],
        first_byte_timeout=1,
    )

    assert result is response
    snapshot = model.llm_request_stat.get_request_stat_info()
    assert snapshot["total_requests"] == 1
    assert snapshot["request_duration_count"] == 1
    model.chat_model.create.assert_called_once()


def test_failed_provider_attempt_is_counted():
    """A request remains counted when the provider raises an exception."""
    model = _make_request_model(create_error=RuntimeError("provider failed"))

    with pytest.raises(RuntimeError, match="provider failed"):
        model._create_with_first_byte_timeout(
            [{"role": "user", "content": "hello"}],
            first_byte_timeout=0,
        )

    snapshot = model.llm_request_stat.get_request_stat_info()
    assert snapshot["total_requests"] == 1
    assert snapshot["request_duration_count"] == 1
    model.chat_model.create.assert_called_once()


class _StreamFailure:
    """Raise a deterministic error while consuming a provider stream."""

    def __iter__(self):
        """Return this object as its own iterator."""
        return self

    def __next__(self):
        """Raise the configured stream failure."""
        raise RuntimeError("stream failed")


def _make_outcome_model(response=None, create_error=None):
    """Build a model fixture for provider request outcome integration tests."""
    model = LLMModel.__new__(LLMModel)
    model.build_parameters_for_chat = MagicMock(return_value={"stream": False})
    model.tokenStat = MagicMock()
    model.llm_request_stat = MagicMock()
    model.llm_request_stat.start_request.return_value = object()
    model.llm_request_stat.record_request.return_value = {"total_requests": 1}
    model.llm_request_stat.record_request_success.return_value = {
        "request_successes": 1,
    }
    model.llm_request_stat.record_request_failure.return_value = {
        "request_failures": 1,
    }
    model.models = []
    model.model = MagicMock()
    if create_error is not None:
        model.model.create.side_effect = create_error
    else:
        model.model.create.return_value = response
    model.content_senders = []
    model.send_content = MagicMock()
    model._record_llm_response_event = MagicMock()
    model._get_first_byte_timeout_config = MagicMock(return_value=(0, False))
    return model


def _make_non_stream_response(content="ok"):
    """Build a minimal non-streaming provider response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


class _ClockAdvancingStream:
    """Advance a mutable clock when a test stream completes or fails."""

    def __init__(self, clock, end_time, error=None):
        """Store the clock, terminal timestamp, and optional terminal error."""
        self.clock = clock
        self.end_time = end_time
        self.error = error

    def __iter__(self):
        """Return this object as its own iterator."""
        return self

    def __next__(self):
        """Advance time and complete or fail stream consumption."""
        self.clock.value = self.end_time
        if self.error is not None:
            raise self.error
        raise StopIteration


def test_non_stream_success_records_full_response_duration():
    """Non-stream timing should end when the complete response is returned."""
    clock = MutableClock(10.0)
    response = _make_non_stream_response()
    model = _make_outcome_model(response)
    model.llm_request_stat = LLMRequestStat(clock=clock)
    model.model.create.side_effect = lambda **_: (
        setattr(clock, "value", 12.5) or response
    )
    model.fix_response_content = MagicMock(return_value="ok")
    model.check_response_content = MagicMock()

    model.call_llm_model([{"role": "user", "content": "hello"}])

    snapshot = model.llm_request_stat.get_request_stat_info(timestamp=12.5)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 2.5

def test_non_stream_duration_excludes_pre_request_and_post_response_work():
    """Duration must include only the provider create request/response interval."""
    clock = MutableClock(10.0)
    response = _make_non_stream_response()
    model = _make_outcome_model(response)
    model.llm_request_stat = LLMRequestStat(clock=clock)

    def build_parameters(*_, **__):
        clock.value = 20.0
        return {"stream": False}

    def create_response(**_):
        clock.value = 23.0
        return response

    def post_process(*_, **__):
        clock.value = 40.0
        return "ok"

    model.build_parameters_for_chat.side_effect = build_parameters
    model.model.create.side_effect = create_response
    model.fix_response_content = MagicMock(side_effect=post_process)
    model.check_response_content = MagicMock()

    model.call_llm_model([{"role": "user", "content": "hello"}])

    snapshot = model.llm_request_stat.get_request_stat_info(timestamp=40.0)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 3.0
    assert snapshot["request_duration_min_sec"] == 3.0
    assert snapshot["request_duration_max_sec"] == 3.0
    assert snapshot["request_duration_p95_sec"] == 3.0



def test_provider_failure_records_full_response_duration():
    """Provider timing should end when request creation raises an error."""
    clock = MutableClock(20.0)
    model = _make_outcome_model()
    model.llm_request_stat = LLMRequestStat(clock=clock)

    def fail_create(**_):
        clock.value = 21.25
        raise RuntimeError("provider failed")

    model.model.create.side_effect = fail_create

    with pytest.raises(RuntimeError, match="provider failed"):
        model.call_llm_model([{"role": "user", "content": "hello"}])

    snapshot = model.llm_request_stat.get_request_stat_info(timestamp=21.25)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 1.25


def test_stream_success_records_duration_after_full_consumption():
    """Streaming timing should end only after the iterator is exhausted."""
    clock = MutableClock(30.0)
    stream = _ClockAdvancingStream(clock, 33.0)
    model = _make_outcome_model(stream)
    model.llm_request_stat = LLMRequestStat(clock=clock)
    model.fix_response_content = MagicMock(return_value="")
    model.check_response_content = MagicMock()

    model.call_llm_model_by_stream([{"role": "user", "content": "hello"}])

    snapshot = model.llm_request_stat.get_request_stat_info(timestamp=33.0)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 3.0


def test_stream_failure_records_duration_at_iteration_error():
    """Streaming timing should end when iterator consumption raises an error."""
    clock = MutableClock(40.0)
    stream = _ClockAdvancingStream(
        clock, 44.0, error=RuntimeError("stream failed")
    )
    model = _make_outcome_model(stream)
    model.llm_request_stat = LLMRequestStat(clock=clock)

    with pytest.raises(RuntimeError, match="stream failed"):
        model.call_llm_model_by_stream(
            [{"role": "user", "content": "hello"}]
        )

    snapshot = model.llm_request_stat.get_request_stat_info(timestamp=44.0)
    assert snapshot["request_duration_count"] == 1
    assert snapshot["request_duration_avg_sec"] == 4.0


def test_non_stream_request_records_success_once():
    """A validated provider response should record one successful request."""
    model = _make_outcome_model(_make_non_stream_response())
    model.fix_response_content = MagicMock(return_value="ok")
    model.check_response_content = MagicMock()

    model.call_llm_model([{"role": "user", "content": "hello"}])

    model.llm_request_stat.record_request_success.assert_called_once_with()
    model.llm_request_stat.record_request_failure.assert_not_called()


def test_provider_exception_records_failure_once():
    """A provider exception should record one failed request."""
    model = _make_outcome_model(create_error=RuntimeError("provider failed"))

    with pytest.raises(RuntimeError, match="provider failed"):
        model.call_llm_model([{"role": "user", "content": "hello"}])

    model.llm_request_stat.record_request_success.assert_not_called()
    model.llm_request_stat.record_request_failure.assert_called_once_with()


def test_response_validation_exception_records_failure_once():
    """Invalid provider content should fail the request exactly once."""
    model = _make_outcome_model(_make_non_stream_response(content=""))
    model.fix_response_content = MagicMock(return_value="")
    model.check_response_content = MagicMock(
        side_effect=TypeError("null response")
    )

    with pytest.raises(TypeError, match="null response"):
        model.call_llm_model([{"role": "user", "content": "hello"}])

    model.llm_request_stat.record_request_success.assert_not_called()
    model.llm_request_stat.record_request_failure.assert_called_once_with()


def test_stream_iteration_exception_records_failure_once():
    """An exception while consuming a started stream should fail the request."""
    model = _make_outcome_model(_StreamFailure())

    with pytest.raises(RuntimeError, match="stream failed"):
        model.call_llm_model_by_stream(
            [{"role": "user", "content": "hello"}]
        )

    model.llm_request_stat.record_request_success.assert_not_called()
    model.llm_request_stat.record_request_failure.assert_called_once_with()


def test_parameter_build_error_does_not_record_request_outcome():
    """A pre-provider parameter error is not an LLM request failure."""
    model = _make_outcome_model()
    model.build_parameters_for_chat.side_effect = ValueError("bad parameters")

    with pytest.raises(ValueError, match="bad parameters"):
        model.call_llm_model([{"role": "user", "content": "hello"}])

    model.llm_request_stat.start_request.assert_not_called()
    model.llm_request_stat.record_request.assert_not_called()
    model.llm_request_stat.record_request_success.assert_not_called()
    model.llm_request_stat.record_request_failure.assert_not_called()


def test_tool_exception_records_one_response_content_error():
    """A regular tool exception should increment the content-error counter once."""
    from topsailai.ai_base.agent_types.tool import exec_tool_func

    def fail_tool():
        """Raise a regular tool execution error."""
        raise ValueError("tool failed")

    with patch(
        "topsailai.ai_base.agent_types.tool._record_llm_response_content_error"
    ) as record_error:
        assert exec_tool_func(fail_tool, {}, "fail_tool") == "tool failed"

    record_error.assert_called_once_with()


@pytest.mark.parametrize(
    ("tool_call_info", "tools", "expected_error"),
    [
        (None, {}, "missing tool_call or arguments error"),
        (MagicMock(func_name="unknown", func_args={}), {}, "no found such as tool"),
    ],
)
def test_invalid_action_records_one_response_content_error(
    tool_call_info, tools, expected_error
):
    """Missing action data and unknown tools should each count once."""
    from topsailai.ai_base.agent_types.tool import StepCallTool

    step_call = StepCallTool()
    step_call.get_tool_call_info = MagicMock(return_value=tool_call_info)

    with patch(
        "topsailai.ai_base.agent_types.tool._record_llm_response_content_error"
    ) as record_error:
        result = step_call.execute_step_action({}, tools, MagicMock())

    assert expected_error in str(result)
    record_error.assert_called_once_with()


def test_successful_tool_does_not_record_response_content_error():
    """A successful tool execution should not increment content errors."""
    from topsailai.ai_base.agent_types.tool import exec_tool_func

    with patch(
        "topsailai.ai_base.agent_types.tool._record_llm_response_content_error"
    ) as record_error:
        assert exec_tool_func(lambda: "ok", {}, "ok_tool") == "ok"

    record_error.assert_not_called()


def test_agent_control_flow_exception_is_not_response_content_error():
    """Agent control-flow exceptions should be re-raised without counting."""
    from topsailai.ai_base.agent_types.exception import AgentEndProcess
    from topsailai.ai_base.agent_types.tool import exec_tool_func

    def stop_agent():
        """Raise an agent control-flow exception."""
        raise AgentEndProcess("stop")

    with patch(
        "topsailai.ai_base.agent_types.tool._record_llm_response_content_error"
    ) as record_error:
        with pytest.raises(AgentEndProcess, match="stop"):
            exec_tool_func(stop_agent, {}, "stop_tool")

    record_error.assert_not_called()


def test_tool_approval_denial_is_not_response_content_error():
    """An approval denial should remain separate from tool content errors."""
    from topsailai.ai_base.agent_types.tool import StepCallTool
    from topsailai.ai_base.tool_approval import ToolApprovalDeniedError

    tool_call = MagicMock(func_name="guarded", func_args={})
    step_call = StepCallTool()
    step_call.get_tool_call_info = MagicMock(return_value=tool_call)

    with patch(
        "topsailai.ai_base.agent_types.tool.exec_tool_func",
        side_effect=ToolApprovalDeniedError("denied"),
    ), patch(
        "topsailai.ai_base.agent_types.tool._record_llm_response_content_error"
    ) as record_error:
        assert step_call.execute_step_action(
            {}, {"guarded": lambda: "ok"}, MagicMock()
        ) == "denied"

    record_error.assert_not_called()
