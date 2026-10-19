"""Immediate first-chunk progress regressions. Author: DawsonLin."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.llm_base import LLMModel
from topsailai.workspace import print_tool
from topsailai.workspace.print_tool import ContentProgress


def make_model(progress, chunks):
    """Build a provider-free model retaining the actual orchestration and sender."""
    model = object.__new__(LLMModel)
    model.tokenStat = MagicMock()
    model.content_senders = [progress]
    model._create_with_first_byte_timeout = MagicMock(return_value=(object(), False))
    model.iter_stream_with_first_byte_timeout = MagicMock(return_value=chunks)
    model._get_llm_request_timing_ticket = MagicMock(return_value=None)
    model._get_stream_chunk_sample_limit = MagicMock(return_value=0)
    model._extract_stream_part = lambda chunk: chunk
    model._extract_stream_content = lambda part: part.content
    model.get_response_usage = MagicMock(return_value=None)
    model._merge_stream_calls = MagicMock()
    model._build_stream_calls = MagicMock(return_value=[])
    model._build_stream_response = lambda content, calls: content
    model.fix_response_content = lambda **kwargs: kwargs["rsp_content"]
    for name in (
        "_observe_stream_usage", "_check_stream_interrupt",
        "_finish_stream_debug_output", "_log_final_stream_usage",
        "check_response_content", "_record_llm_response_event",
    ):
        setattr(model, name, MagicMock())
    return model


@pytest.mark.parametrize("mode", ["stats", "stats_7s", "bar"])
@pytest.mark.parametrize("first", [None, SimpleNamespace(content="")])
def test_first_chunk_renders_before_next_chunk_and_preserves_throttle(mode, first):
    """Even an unextractable chunk renders once without waiting for content."""
    output = StringIO()
    clock = SimpleNamespace(monotonic=lambda: 100.0)
    progress = ContentProgress(mode=mode)

    def chunks():
        """Inspect output before handing the consumer any subsequent data."""
        yield first
        assert output.getvalue().count("Generating") == 1
        assert "0 chars" in output.getvalue()
        assert output.flush.call_count == 1
        yield SimpleNamespace(content="hello")
        yield SimpleNamespace(content=" world")
        assert output.getvalue().count("Generating") == 1
        assert progress._char_count == 11

    output.flush = MagicMock(wraps=output.flush)
    model = make_model(progress, chunks())
    content_only_sender = SimpleNamespace(send=MagicMock())
    model.content_senders.append(content_only_sender)
    with patch.object(print_tool, "sys", SimpleNamespace(stdout=output)), patch.object(
        print_tool, "time", clock
    ):
        assert model._call_llm_model_by_stream_owned_body([])[1] == "hello world"
    assert output.getvalue().count("Generating") == 1
    assert output.getvalue().endswith("\n")
    assert output.flush.call_count == 2
    assert content_only_sender.send.call_count == 2


def test_next_request_and_retry_reset_reused_sender():
    """A new attempt immediately renders even after completion or interruption."""
    output = StringIO()
    progress = ContentProgress(mode="stats_7s")
    model = make_model(progress, iter(()))

    def interrupted():
        """Leave the first request unfinished after receiving its first chunk."""
        yield SimpleNamespace(content="old")
        raise RuntimeError("stream interrupted")

    with patch.object(print_tool, "sys", SimpleNamespace(stdout=output)), patch.object(
        print_tool, "time", SimpleNamespace(monotonic=lambda: 100.0)
    ):
        model.iter_stream_with_first_byte_timeout.return_value = interrupted()
        with pytest.raises(RuntimeError, match="stream interrupted"):
            model._call_llm_model_by_stream_owned_body([])
        for content in ("retry", "next"):
            model.iter_stream_with_first_byte_timeout.return_value = iter([
                SimpleNamespace(content=""), SimpleNamespace(content=content),
            ])
            model._call_llm_model_by_stream_owned_body([])
            assert progress._char_count == len(content)
    assert output.getvalue().count("Generating") == 3
    assert output.getvalue().count("Generating... 0 chars,") == 3
    assert output.getvalue().count("\n") == 2


def test_stats_7s_refresh_boundary_after_first_chunk():
    """Only the initial notification bypasses the interval, not later text."""
    clock = MagicMock()
    clock.monotonic.return_value = 100.0
    output = StringIO()
    progress = ContentProgress(mode="stats_7s")
    with patch.object(print_tool, "sys", SimpleNamespace(stdout=output)), patch.object(
        print_tool, "time", clock
    ):
        progress.start_stream()
        clock.monotonic.return_value = 106.9
        progress.send("abc")
        assert output.getvalue().count("Generating") == 1
        clock.monotonic.return_value = 107.0
        progress.send("d")
    assert output.getvalue().count("Generating") == 2
    assert "4 chars" in output.getvalue()


def test_dots_and_empty_stream_have_no_synthetic_output():
    """Notifications add no dots, and a stream with no chunks never starts."""
    output = StringIO()
    progress = ContentProgress(mode="dots")
    model = make_model(progress, iter([
        SimpleNamespace(content=""), SimpleNamespace(content="a"),
        SimpleNamespace(content="b"),
    ]))
    with patch.object(print_tool, "sys", SimpleNamespace(stdout=output)):
        model._call_llm_model_by_stream_owned_body([])
        assert output.getvalue() == "..\n"
        progress = ContentProgress(mode="stats_7s")
        model = make_model(progress, iter(()))
        model._call_llm_model_by_stream_owned_body([])
    assert output.getvalue() == "..\n\n"
    assert progress._start_time is None
