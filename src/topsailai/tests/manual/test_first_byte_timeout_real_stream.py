"""
Manual test for first-byte timeout with a realistic OpenAI Stream object.

This test creates a mock httpx.Response that blocks on iter_bytes() to simulate
a real streaming LLM that hangs before sending the first chunk. It then verifies
that iter_stream_with_first_byte_timeout logs a warning within the timeout.
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import MagicMock, patch

# Ensure project source is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import httpx
import openai

from topsailai.ai_base.llm_base import LLMModel


class BlockingResponse:
    """Mock httpx.Response whose iter_bytes blocks indefinitely."""

    def __init__(self):
        self.request = MagicMock()
        self._closed = False
        self._block_event = threading.Event()

    def iter_bytes(self, chunk_size=None):
        # Block until explicitly released (or until test timeout kills us).
        self._block_event.wait()
        if self._closed:
            return
        yield b""

    def close(self):
        self._closed = True
        self._block_event.set()


class TestFirstByteTimeoutRealStream(unittest.TestCase):
    def _create_model(self):
        model = LLMModel.__new__(LLMModel)
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

    @patch("topsailai.ai_base.llm_base.print_warning")
    def test_real_openai_stream_timeout_logs_warning(self, mock_print_warning):
        """A real OpenAI Stream whose first chunk blocks must trigger the warning."""
        # Build a minimal OpenAI client so Stream.__init__ can run.
        client = openai.OpenAI(api_key="test-key")
        response = BlockingResponse()
        stream = openai.Stream(
            cast_to=openai.types.chat.ChatCompletionChunk,
            response=response,
            client=client,
        )

        model = self._create_model()
        timeout_seconds = 0.5

        start = time.monotonic()
        chunks = list(
            model.iter_stream_with_first_byte_timeout(
                stream, first_byte_timeout=timeout_seconds
            )
        )
        elapsed = time.monotonic() - start

        print(f"elapsed: {elapsed:.2f}s, chunks: {len(chunks)}")
        self.assertLess(elapsed, timeout_seconds + 0.5)
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("LLM Service", warning_msg)
        self.assertIn("first byte timeout threshold reached/exceeded", warning_msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
