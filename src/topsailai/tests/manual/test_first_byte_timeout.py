#!/usr/bin/env python3
"""Manual test for first-byte timeout logic in ai_base/llm_base.py.

This script simulates a streaming LLM response whose first byte blocks for
longer than TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT and verifies the behavior of
LLMModel.iter_stream_with_first_byte_timeout and the create() watchdog in
LLMModel.call_llm_model_by_stream.

Run from the project root:
    cd /TopsailAI/src/topsailai
    python tests/manual/test_first_byte_timeout.py
"""

import os
import sys
import time
import openai
from unittest.mock import MagicMock, patch

# Ensure the project source tree is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from topsailai.ai_base.llm_base import LLMModel


class FakeChunk:
    """Minimal stand-in for an OpenAI streaming chunk."""

    def __init__(self, content=""):
        self.choices = [MagicMock()]
        self.choices[0].delta.content = content
        self.choices[0].delta.tool_calls = None
        self.usage = None


class FakeStream:
    """Fake streaming iterator that sleeps before returning the first chunk."""

    def __init__(self, chunks, first_chunk_delay=0.0):
        self.chunks = chunks
        self.first_chunk_delay = first_chunk_delay
        self.index = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.index == 0 and self.first_chunk_delay > 0:
            time.sleep(self.first_chunk_delay)
        if self.index >= len(self.chunks):
            raise StopIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk

    def close(self):
        self.closed = True


def create_model():
    """Create a minimally initialized LLMModel instance for testing."""
    with patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None):
        model = LLMModel()
    model.models = []
    model.model = MagicMock()
    model.tokenStat = MagicMock()
    model.model_config = {"api_key": "test-key"}
    model.model_name = "test-model"
    model.temperature = 0.7
    model.max_tokens = 4096
    model.top_p = 1.0
    model.frequency_penalty = 0.0
    model.content_senders = []
    model.hooks = {}
    return model


def test_warning_mode():
    """Timeout exceeded without raise: warning printed and iteration stops."""
    print("\n=== Test: warning mode (timeout exceeded, no raise) ===")
    model = create_model()
    stream = FakeStream([FakeChunk("hello")], first_chunk_delay=2.0)

    start = time.monotonic()
    result = list(model.iter_stream_with_first_byte_timeout(stream, first_byte_timeout=0.5))
    elapsed = time.monotonic() - start

    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  result length: {len(result)}")
    print(f"  stream closed: {stream.closed}")

    assert len(result) == 0, "Expected empty result after timeout"
    assert elapsed < 1.5, "Should not wait for the full stream delay"
    assert stream.closed, "Stream should be closed after timeout"
    print("  PASS")


def test_raise_mode():
    """Timeout exceeded with raise_on_timeout=True: APITimeoutError raised."""
    print("\n=== Test: raise mode (timeout exceeded, raise enabled) ===")
    model = create_model()
    stream = FakeStream([FakeChunk("hello")], first_chunk_delay=2.0)

    start = time.monotonic()
    try:
        list(model.iter_stream_with_first_byte_timeout(
            stream, first_byte_timeout=0.5, raise_on_timeout=True
        ))
        print("  FAIL: expected openai.APITimeoutError")
        return False
    except openai.APITimeoutError as exc:
        elapsed = time.monotonic() - start
        print(f"  elapsed: {elapsed:.2f}s")
        print(f"  exception: {exc}")
        print(f"  stream closed: {stream.closed}")
        assert elapsed < 1.5, "Should not wait for the full stream delay"
        assert stream.closed, "Stream should be closed after timeout"
        assert "First byte timeout" in str(exc), "Exception message should mention first byte timeout"
        print("  PASS")
        return True


def test_disabled():
    """first_byte_timeout=0 disables the check and lets the stream block."""
    print("\n=== Test: disabled (first_byte_timeout=0) ===")
    model = create_model()
    stream = FakeStream([FakeChunk("hello")], first_chunk_delay=0.5)

    start = time.monotonic()
    result = list(model.iter_stream_with_first_byte_timeout(stream, first_byte_timeout=0))
    elapsed = time.monotonic() - start

    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  result length: {len(result)}")

    assert len(result) == 1, "Expected one chunk when timeout is disabled"
    assert elapsed >= 0.5, "Should block for the stream delay"
    print("  PASS")


def test_fast_first_byte():
    """Fast first byte yields all chunks without warning or error."""
    print("\n=== Test: fast first byte ===")
    model = create_model()
    stream = FakeStream([FakeChunk("hello"), FakeChunk(" world")], first_chunk_delay=0.1)

    start = time.monotonic()
    result = list(model.iter_stream_with_first_byte_timeout(stream, first_byte_timeout=2.0))
    elapsed = time.monotonic() - start

    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  result length: {len(result)}")

    assert len(result) == 2, "Expected both chunks"
    assert elapsed < 1.0, "Should not trigger timeout"
    print("  PASS")


def test_empty_stream():
    """Empty stream terminates cleanly without warning."""
    print("\n=== Test: empty stream ===")
    model = create_model()
    stream = FakeStream([], first_chunk_delay=0.0)

    result = list(model.iter_stream_with_first_byte_timeout(stream, first_byte_timeout=0.5))

    print(f"  result length: {len(result)}")
    assert len(result) == 0, "Expected empty result"
    print("  PASS")


def test_create_slow_watchdog():
    """Slow chat_model.create() triggers the first-byte timeout warning."""
    print("\n=== Test: create() slow watchdog ===")
    os.environ["TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT"] = "1"
    os.environ["TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE"] = "0"

    try:
        model = create_model()
        fake_stream = FakeStream([FakeChunk("hello")], first_chunk_delay=0.0)

        def slow_create(*args, **kwargs):
            time.sleep(2.0)
            return fake_stream

        model.model = MagicMock()
        model.model.create.side_effect = slow_create

        with patch("topsailai.ai_base.llm_base.print_warning") as mock_print_warning:
            start = time.monotonic()
            response, content = model.call_llm_model_by_stream([{"role": "user", "content": "test"}])
            elapsed = time.monotonic() - start

            print(f"  elapsed: {elapsed:.2f}s")
            print(f"  warning calls: {mock_print_warning.call_count}")
            assert elapsed >= 1.5, "Should wait for slow create()"
            assert mock_print_warning.call_count >= 1, "Expected warning to be logged"
            warning_msg = str(mock_print_warning.call_args[0][0])
            assert "LLM first byte took" in warning_msg, f"Unexpected warning: {warning_msg}"
            print("  PASS")
    finally:
        os.environ.pop("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT", None)
        os.environ.pop("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE", None)


def test_env_vars_via_call_llm_model_by_stream():
    """Env vars are honored when invoked through call_llm_model_by_stream."""
    print("\n=== Test: env vars via call_llm_model_by_stream ===")
    os.environ["TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT"] = "1"
    os.environ["TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE"] = "1"

    try:
        model = create_model()
        fake_stream = FakeStream([FakeChunk("hello")], first_chunk_delay=3.0)
        # chat_model is a property that returns self.model; override self.model
        # so that chat_model.create() returns our fake stream.
        model.model = MagicMock()
        model.model.create.return_value = fake_stream

        start = time.monotonic()
        try:
            model.call_llm_model_by_stream([{"role": "user", "content": "test"}])
            print("  FAIL: expected openai.APITimeoutError")
            return False
        except openai.APITimeoutError as exc:
            elapsed = time.monotonic() - start
            print(f"  elapsed: {elapsed:.2f}s")
            print(f"  exception: {exc}")
            print(f"  stream closed: {fake_stream.closed}")
            assert elapsed < 2.5, "Should timeout quickly based on env var"
            assert fake_stream.closed, "Stream should be closed after timeout"
            print("  PASS")
            return True
    finally:
        os.environ.pop("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT", None)
        os.environ.pop("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE", None)


def main():
    print("First-byte timeout manual test")
    print("Project: /TopsailAI/src/topsailai")
    print("Target: topsailai.ai_base.llm_base.LLMModel")

    tests = [
        test_warning_mode,
        test_raise_mode,
        test_disabled,
        test_fast_first_byte,
        test_empty_stream,
        test_create_slow_watchdog,
        test_env_vars_via_call_llm_model_by_stream,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"  FAIL: {exc}")
            failed.append(test.__name__)

    print("\n" + "=" * 50)
    if failed:
        print(f"FAILED ({len(failed)}/{len(tests)}): {failed}")
        return 1
    print(f"All {len(tests)} tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
