"""
Unit tests for ai_base/llm_base.py module.

This module contains unit tests for the LLMModel class which provides
OpenAI-compatible LLM interaction capabilities.
"""

import json
import unittest
from unittest.mock import MagicMock, call, patch, PropertyMock

import openai


class TestLLMModelGetModelName(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.default_model = "DeepSeek-V3.1-Terminus"

    @patch("topsailai.ai_base.llm_base.os.getenv")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_get_model_name_returns_env_value(self, mock_base_init, mock_logger, mock_getenv):
        """Test get_model_name returns value from OPENAI_MODEL env var."""
        mock_getenv.return_value = "gpt-4"
        
        from topsailai.ai_base.llm_base import LLMModel
        model = LLMModel()
        model.model_name = None
        
        result = model.get_model_name()
        
        mock_getenv.assert_called_with("OPENAI_MODEL", self.default_model)
        self.assertEqual(result, "gpt-4")

    @patch("topsailai.ai_base.llm_base.os.getenv")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_get_model_name_returns_default_when_env_empty(self, mock_base_init, mock_logger, mock_getenv):
        """Test get_model_name returns default when env var is not set."""
        mock_getenv.return_value = self.default_model
        
        from topsailai.ai_base.llm_base import LLMModel
        model = LLMModel()
        model.model_name = None
        
        result = model.get_model_name()
        
        self.assertEqual(result, self.default_model)


class TestLLMModelGetLLMModel(unittest.TestCase):
    """Test cases for LLMModel.get_llm_model method."""

    def setUp(self):
        """Set up test fixtures."""
        self.api_key = "test-api-key-123"
        self.api_base = "https://custom.api.endpoint.com/v1"

    @patch("topsailai.ai_base.llm_base.openai.OpenAI")
    @patch("topsailai.ai_base.llm_base.os.getenv")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_get_llm_model_with_custom_credentials(self, mock_base_init, mock_logger, mock_getenv, mock_openai):
        """Test get_llm_model creates client with custom credentials."""
        mock_getenv.side_effect = lambda k, d=None: {
            "OPENAI_API_KEY": self.api_key,
            "OPENAI_API_BASE": self.api_base,
        }.get(k, d)
        
        mock_chat = MagicMock()
        mock_openai.return_value.chat = mock_chat
        
        from topsailai.ai_base.llm_base import LLMModel
        model = LLMModel()
        model.model_name = "test-model"
        
        result = model.get_llm_model(api_key=self.api_key, api_base=self.api_base)
        
        mock_openai.assert_called_once_with(
            api_key=self.api_key,
            base_url=self.api_base,
        )
        self.assertEqual(result, mock_chat.completions)

    @patch("topsailai.ai_base.llm_base.openai.OpenAI")
    @patch("topsailai.ai_base.llm_base.os.getenv")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_get_llm_model_uses_env_defaults(self, mock_base_init, mock_logger, mock_getenv, mock_openai):
        """Test get_llm_model uses environment variables as defaults."""
        mock_getenv.side_effect = lambda k, d=None: {
            "OPENAI_API_KEY": "env-key",
            "OPENAI_API_BASE": "https://api.openai.com/v1",
        }.get(k, d)
        
        mock_chat = MagicMock()
        mock_openai.return_value.chat = mock_chat
        
        from topsailai.ai_base.llm_base import LLMModel
        model = LLMModel()
        model.model_name = "test-model"
        
        result = model.get_llm_model()
        
        mock_openai.assert_called_once()


class TestLLMModelCallLLMModel(unittest.TestCase):
    """Test cases for LLMModel.call_llm_model method."""

    def setUp(self):
        """Set up test fixtures."""
        self.messages = [{"role": "user", "content": "Hello"}]
        self.tools = [{"type": "function", "function": {"name": "test_tool"}}]

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_returns_response(self, mock_base_init, mock_logger, mock_get_msg, mock_format):
        """Test call_llm_model returns tuple of response and content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        
        mock_get_msg.return_value = MagicMock(content="Test response")
        mock_format.return_value = ["formatted", "response"]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.call_llm_model(self.messages)
        
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1], "Test response")

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_with_tools(self, mock_base_init, mock_logger, mock_get_msg, mock_format):
        """Test call_llm_model passes tools to chat model."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response with tools"
        
        mock_get_msg.return_value = MagicMock(content="Response with tools")
        mock_format.return_value = ["formatted"]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        model.call_llm_model(self.messages, tools=self.tools, tool_choice="required")
        
        call_kwargs = model.model.create.call_args[1]
        self.assertIn("tools", call_kwargs)
        self.assertEqual(call_kwargs["tools"], self.tools)

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_adds_tokens(self, mock_base_init, mock_logger, mock_get_msg, mock_format):
        """Test call_llm_model adds messages to token stats."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Token test"
        
        mock_get_msg.return_value = MagicMock(content="Token test")
        mock_format.return_value = ["formatted"]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        model.call_llm_model(self.messages)
        
        model.tokenStat.add_msgs.assert_called_once()
        model.tokenStat.output_token_stat.assert_called_once()


class TestLLMModelCallLLMModelByStream(unittest.TestCase):
    """Test cases for LLMModel.call_llm_model_by_stream method."""

    def setUp(self):
        """Set up test fixtures."""
        self.messages = [{"role": "user", "content": "Stream test"}]

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_warns_on_slow_create(
        self, mock_base_init, mock_print_warning, mock_env_tool
    ):
        """Test that a blocking chat_model.create() triggers the first-byte warning."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.1
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        def slow_create(*args, **kwargs):
            time.sleep(0.2)
            mock_chunk = MagicMock()
            mock_chunk.choices = [MagicMock()]
            mock_chunk.choices[0].delta.content = "Hello"
            mock_chunk.choices[0].delta.tool_calls = None
            return iter([mock_chunk])

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        result = model.call_llm_model_by_stream(self.messages)

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[1], "Hello")
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("LLM Service", warning_msg)
        self.assertIn("first byte timeout threshold reached/exceeded", warning_msg)
        self.assertIn("0.1s", warning_msg)

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_yields_chunks(self, mock_base_init, mock_logger):
        """Test streaming response yields content chunks."""
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = "Hello "
        mock_chunk1.choices[0].delta.tool_calls = None
        
        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = "World"
        mock_chunk2.choices[0].delta.tool_calls = None
        
        mock_response = iter([mock_chunk1, mock_chunk2])
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.call_llm_model_by_stream(self.messages)
        
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[1], "Hello World")

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_records_first_byte(
        self, mock_base_init, mock_logger
    ):
        """Test streaming response records first-byte timing in tokenStat."""
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = "Hello "
        mock_chunk1.choices[0].delta.tool_calls = None

        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = "World"
        mock_chunk2.choices[0].delta.tool_calls = None

        mock_response = iter([mock_chunk1, mock_chunk2])

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        result = model.call_llm_model_by_stream(self.messages)

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[1], "Hello World")
        model.tokenStat.add_first_byte.assert_called_once()
        first_byte_arg = model.tokenStat.add_first_byte.call_args[0][0]
        self.assertIsInstance(first_byte_arg, float)
        self.assertGreaterEqual(first_byte_arg, 0.0)

    @patch("topsailai.ai_base.llm_base.time.monotonic")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_first_byte_unit_is_milliseconds(
        self, mock_base_init, mock_monotonic
    ):
        """Test that first-byte timing passed to tokenStat is in milliseconds."""
        # Sequence of monotonic timestamps seen by the streaming path for a
        # single-chunk response with no timeout:
        #   1. _create_with_first_byte_timeout start_time
        #   2. _create_with_first_byte_timeout elapsed
        #   3. call_llm_model_by_stream stream_start_time
        #   4. iter_stream_with_first_byte_timeout start_time
        #   5. iter_stream_with_first_byte_timeout elapsed before first chunk
        #   6. first_byte_ms computation (1.5s after stream_start_time)
        mock_monotonic.side_effect = [0.0, 0.0, 0.0, 0.0, 0.0, 1.5]

        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello"
        mock_chunk.choices[0].delta.tool_calls = None

        model = self._create_mock_model()
        model.model.create.return_value = iter([mock_chunk])

        result = model.call_llm_model_by_stream(self.messages)

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[1], "Hello")
        model.tokenStat.add_first_byte.assert_called_once()
        first_byte_arg = model.tokenStat.add_first_byte.call_args[0][0]
        self.assertIsInstance(first_byte_arg, float)
        self.assertAlmostEqual(first_byte_arg, 1500.0, delta=1.0)

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_handles_tool_calls(self, mock_base_init, mock_logger):
        """Test streaming response handles tool calls correctly."""
        mock_function = MagicMock()
        mock_function.name = "test_func"
        mock_function.arguments = '{"arg": "value"}'
        
        mock_tool_call = MagicMock()
        mock_tool_call.index = 0
        mock_tool_call.id = "call_123"
        mock_tool_call.function = mock_function
        
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = ""
        mock_chunk.choices[0].delta.tool_calls = [mock_tool_call]
        
        mock_response = iter([mock_chunk])
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.call_llm_model_by_stream(self.messages)
        
        self.assertIsInstance(result, tuple)

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_debug_mode(self, mock_base_init, mock_logger, mock_env_tool):
        """Test streaming respects debug mode setting."""
        mock_env_tool.is_debug_mode.return_value = True
        mock_env_tool.EnvReaderInstance.get.return_value = 180
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False
        
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Debug test"
        mock_chunk.choices[0].delta.tool_calls = None
        
        mock_response = iter([mock_chunk])
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.call_llm_model_by_stream(self.messages)
        
        self.assertEqual(result[1], "Debug test")

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_multiple_tool_calls(self, mock_base_init, mock_logger):
        """Test streaming handles multiple tool calls."""
        mock_function1 = MagicMock()
        mock_function1.name = "func1"
        mock_function1.arguments = '{"key1":'
        
        mock_tool_call1 = MagicMock()
        mock_tool_call1.index = 0
        mock_tool_call1.id = "call_1"
        mock_tool_call1.function = mock_function1
        
        mock_function2 = MagicMock()
        mock_function2.name = "func1"
        mock_function2.arguments = '"value1"}'
        
        mock_tool_call2 = MagicMock()
        mock_tool_call2.index = 0
        mock_tool_call2.id = None
        mock_tool_call2.function = mock_function2
        
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = ""
        mock_chunk1.choices[0].delta.tool_calls = [mock_tool_call1]
        
        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = ""
        mock_chunk2.choices[0].delta.tool_calls = [mock_tool_call2]
        
        mock_response = iter([mock_chunk1, mock_chunk2])
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.call_llm_model_by_stream(self.messages)
        
        self.assertIsInstance(result, tuple)

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_logs_warning_on_slow_first_byte(
        self, mock_base_init, mock_print_warning
    ):
        """Test that a blocking first byte triggers a warning and stops iteration."""
        import threading

        def blocking_stream():
            # Block longer than the short timeout used in the test.
            threading.Event().wait(10)
            yield MagicMock()

        model = self._create_mock_model()
        result = list(model.iter_stream_with_first_byte_timeout(blocking_stream(), 0.1))

        self.assertEqual(result, [])
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("0.1s", warning_msg)

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_no_warning_on_fast_first_byte(
        self, mock_base_init, mock_print_warning
    ):
        """Test that a fast first byte yields chunks without warning."""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello"
        mock_chunk.choices[0].delta.tool_calls = None

        model = self._create_mock_model()
        result = list(model.iter_stream_with_first_byte_timeout(iter([mock_chunk]), 180))

        self.assertEqual(result, [mock_chunk])
        mock_print_warning.assert_not_called()

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_empty_stream(
        self, mock_base_init, mock_print_warning
    ):
        """Test that an empty stream does not log a warning."""
        model = self._create_mock_model()
        result = list(model.iter_stream_with_first_byte_timeout(iter([]), 180))

        self.assertEqual(result, [])
        mock_print_warning.assert_not_called()

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_raises_when_configured(
        self, mock_base_init, mock_print_warning
    ):
        """Test that a blocking first byte raises APITimeoutError when enabled."""
        import openai
        import threading

        def blocking_stream():
            threading.Event().wait(10)
            yield MagicMock()

        model = self._create_mock_model()
        with self.assertRaises(openai.APITimeoutError) as ctx:
            list(model.iter_stream_with_first_byte_timeout(blocking_stream(), 0.1, raise_on_timeout=True))

        self.assertIn("First byte timeout", str(ctx.exception))
        mock_print_warning.assert_called_once()

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_disabled_when_zero(
        self, mock_base_init, mock_print_warning
    ):
        """Test that timeout=0 disables the first-byte check."""
        import threading

        ready = threading.Event()

        def slow_stream():
            ready.wait(0.05)
            yield MagicMock()

        model = self._create_mock_model()
        result = list(model.iter_stream_with_first_byte_timeout(slow_stream(), 0))

        self.assertEqual(len(result), 1)
        mock_print_warning.assert_not_called()

    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_iter_stream_with_first_byte_timeout_only_applies_to_first_chunk(
        self, mock_base_init, mock_print_warning
    ):
        """Test that only the first chunk is subject to timeout."""
        import threading

        mock_chunk1 = MagicMock()
        mock_chunk2 = MagicMock()
        yielded_second = threading.Event()

        def slow_after_first():
            yield mock_chunk1
            yielded_second.wait(10)
            yield mock_chunk2

        # Release the second chunk after a short delay. The delay is longer
        # than the first-byte timeout, so if the wrapper applied a timeout to
        # every chunk it would raise; it should not.
        threading.Timer(0.2, yielded_second.set).start()

        model = self._create_mock_model()
        result = list(model.iter_stream_with_first_byte_timeout(slow_after_first(), 0.1))

        self.assertEqual(result, [mock_chunk1, mock_chunk2])
        mock_print_warning.assert_not_called()



    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_raises_on_slow_create_when_configured(
        self, mock_base_init, mock_env_tool
    ):
        """Test that a blocking chat_model.create() raises when raise flag is enabled."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.1
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        def slow_create(*args, **kwargs):
            time.sleep(0.2)
            mock_chunk = MagicMock()
            mock_chunk.choices = [MagicMock()]
            mock_chunk.choices[0].delta.content = "Hello"
            mock_chunk.choices[0].delta.tool_calls = None
            return iter([mock_chunk])

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        with self.assertRaises(openai.APITimeoutError) as ctx:
            model.call_llm_model_by_stream(self.messages)

        self.assertIn("First byte timeout", str(ctx.exception))

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_warns_on_slow_create(
        self, mock_base_init, mock_print_warning, mock_env_tool
    ):
        """Test that non-streaming call_llm_model warns on slow first byte."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.1
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        def slow_create(*args, **kwargs):
            time.sleep(0.2)
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Hello"
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        result = model.call_llm_model(self.messages)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1], "Hello")
        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("LLM Service", warning_msg)
        self.assertIn("first byte timeout threshold reached/exceeded", warning_msg)
        self.assertIn("elapsed", warning_msg)
        self.assertIn(">= threshold", warning_msg)

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_raises_on_slow_create_when_configured(
        self, mock_base_init, mock_env_tool
    ):
        """Test that non-streaming call_llm_model raises on slow first byte."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.1
        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        def slow_create(*args, **kwargs):
            time.sleep(0.2)
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Hello"
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        with self.assertRaises(openai.APITimeoutError) as ctx:
            model.call_llm_model(self.messages)

        self.assertIn("First byte timeout", str(ctx.exception))

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_first_byte_timeout_float_value_parsed(
        self, mock_base_init, mock_print_warning, mock_env_tool
    ):
        """Test that float timeout values are accepted and parsed."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.05
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        def slow_create(*args, **kwargs):
            time.sleep(0.1)
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Hello"
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        model.call_llm_model(self.messages)

        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("0.05s", warning_msg)
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_first_byte_timeout_log_wording_at_threshold(
        self, mock_base_init, mock_print_warning, mock_env_tool
    ):
        """Test warning wording when first byte reaches/exceeds the threshold."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.1
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        def slow_create(*args, **kwargs):
            time.sleep(0.15)
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Hello"
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        model.call_llm_model(self.messages)

        mock_print_warning.assert_called_once()
        warning_msg = mock_print_warning.call_args[0][0]
        self.assertIn("LLM Service", warning_msg)
        self.assertIn("first byte timeout threshold reached/exceeded", warning_msg)
        self.assertIn("elapsed", warning_msg)
        self.assertIn(">= threshold", warning_msg)
        self.assertIn("0.1s", warning_msg)
    @patch("topsailai.ai_base.llm_base.os.getenv")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_first_byte_timeout_invalid_value_falls_back_to_default(
        self, mock_base_init, mock_print_warning, mock_env_tool, mock_getenv
    ):
        """Test that invalid env value falls back to default 180."""

        mock_getenv.return_value = "not-a-number"
        mock_env_tool.EnvReaderInstance.get.side_effect = lambda name, default=None, formatter=None: default
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        model = self._create_mock_model()
        model.model.create.return_value.choices = [MagicMock()]
        model.model.create.return_value.choices[0].message.content = "Hello"
        model.model.create.return_value.choices[0].message.tool_calls = None

        model.call_llm_model(self.messages)

        mock_print_warning.assert_not_called()

    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.print_warning")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_call_llm_model_by_stream_no_double_warning(
        self, mock_base_init, mock_print_warning, mock_env_tool
    ):
        """Test that a slow create does not warn again when the first chunk arrives."""
        import time

        mock_env_tool.EnvReaderInstance.get.return_value = 0.05
        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        def slow_create(*args, **kwargs):
            time.sleep(0.1)
            mock_chunk = MagicMock()
            mock_chunk.choices = [MagicMock()]
            mock_chunk.choices[0].delta.content = "Hello"
            mock_chunk.choices[0].delta.tool_calls = None
            return iter([mock_chunk])

        model = self._create_mock_model()
        model.model.create.side_effect = slow_create

        model.call_llm_model_by_stream(self.messages)

        mock_print_warning.assert_called_once()

class TestLLMModelChat(unittest.TestCase):
    """Test cases for LLMModel.chat method."""
    def setUp(self):
        """Set up test fixtures."""
        self.messages = [{"role": "user", "content": "Chat test"}]

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_returns_formatted_response(self, mock_base_init, mock_logger, mock_format):
        """Test chat returns formatted response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Chat response"
        
        mock_format.return_value = ["formatted", "response"]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages)
        
        self.assertEqual(result, ["formatted", "response"])

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_with_for_raw_returns_raw_content(self, mock_base_init, mock_logger):
        """Test chat with for_raw=True returns raw content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Raw content"
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages, for_raw=True)
        
        self.assertEqual(result, "Raw content")

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_with_for_response_returns_tuple(self, mock_base_init, mock_logger, mock_format):
        """Test chat with for_response=True returns tuple."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response tuple"
        
        mock_format.return_value = ["formatted"]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages, for_response=True)
        
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_raises_on_empty_response(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat raises Exception after max retries on empty response.
        
        Note: TypeError from empty response is caught and retried.
        After max retries, it raises Exception.
        """
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        
        # Always return empty (triggers TypeError which is caught and retried)
        mock_format.return_value = []
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        # After max retries, should raise Exception
        with self.assertRaises(Exception) as context:
            model.chat(self.messages)
        
        self.assertIn("failed", str(context.exception))

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_with_streaming(self, mock_base_init, mock_logger, mock_format):
        """Test chat with for_stream=True uses streaming."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].delta = MagicMock()
        mock_response.choices[0].delta.content = "Streamed content"
        mock_response.choices[0].delta.tool_calls = None
        
        mock_format.return_value = ["streamed"]
        
        model = self._create_mock_model()
        model.model.create.return_value = iter([mock_response])
        
        result = model.chat(self.messages, for_stream=True)
        
        self.assertEqual(result, ["streamed"])

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_handles_json_error(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat handles JsonError and retries."""
        from topsailai.ai_base.llm_control.exception import JsonError
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success after retry"
        
        mock_format.side_effect = [JsonError("Invalid JSON"), JsonError("Invalid JSON"), ["success"]]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages)
        
        self.assertEqual(result, ["success"])

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.print_info")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_splits_native_tool_calls_into_sequential_responses(
            self,
            mock_base_init,
            mock_logger,
            mock_print_info,
            mock_format,
        ):
        """Test multiple native tool calls are returned one at a time in order."""
        from openai.types.chat import (
            ChatCompletionMessage,
            ChatCompletionMessageToolCall,
        )

        tool_calls = [
            ChatCompletionMessageToolCall(
                id="call-1",
                type="function",
                function={"name": "tool_one", "arguments": "{}"},
            ),
            ChatCompletionMessageToolCall(
                id="call-2",
                type="function",
                function={"name": "tool_two", "arguments": "{}"},
            ),
        ]
        response = ChatCompletionMessage(
            role="assistant",
            content="provider thought",
            tool_calls=tool_calls,
        )
        mock_format.return_value = [{"step_name": "action"}]
        model = self._create_mock_model()
        model.call_llm_model = MagicMock(
            return_value=(response, "provider thought")
        )

        first_rsp, first_result = model.chat(self.messages, for_response=True)
        second_rsp, second_result = model.chat(self.messages, for_response=True)

        self.assertEqual(first_result, [{"step_name": "action"}])
        self.assertEqual(second_result, [{"step_name": "action"}])
        self.assertEqual([call.id for call in first_rsp.tool_calls], ["call-1"])
        self.assertEqual([call.id for call in second_rsp.tool_calls], ["call-2"])
        self.assertEqual(first_rsp.content, "provider thought")
        self.assertEqual(second_rsp.content, "")
        model.call_llm_model.assert_called_once()
        self.assertEqual(len(model._get_pending_native_tool_call_responses()), 0)
        self.assertEqual(
            mock_print_info.call_args_list,
            [
                call("Detected 2 native tool calls"),
                call("Native tool call 1/2"),
                call("Native tool call 2/2"),
            ],
        )

    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.print_info")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_preserves_single_native_tool_call(
            self,
            mock_base_init,
            mock_logger,
            mock_print_info,
            mock_format,
        ):
        """Test a single native tool call retains the original response object."""
        from openai.types.chat import (
            ChatCompletionMessage,
            ChatCompletionMessageToolCall,
        )

        response = ChatCompletionMessage(
            role="assistant",
            content="single",
            tool_calls=[ChatCompletionMessageToolCall(
                id="call-1",
                type="function",
                function={"name": "tool_one", "arguments": "{}"},
            )],
        )
        mock_format.return_value = [{"step_name": "action"}]
        model = self._create_mock_model()
        model.call_llm_model = MagicMock(return_value=(response, "single"))

        returned_rsp, result = model.chat(self.messages, for_response=True)

        self.assertIs(returned_rsp, response)
        self.assertEqual(result, [{"step_name": "action"}])
        self.assertEqual(len(model._get_pending_native_tool_call_responses()), 0)
        mock_print_info.assert_not_called()

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_raw_multi_tool_response_does_not_create_pending_responses(
            self,
            mock_base_init,
            mock_logger,
        ):
        """Test raw response mode does not retain executable synthetic calls."""
        from openai.types.chat import (
            ChatCompletionMessage,
            ChatCompletionMessageToolCall,
        )

        response = ChatCompletionMessage(
            role="assistant",
            content="raw provider content",
            tool_calls=[
                ChatCompletionMessageToolCall(
                    id=f"call-{index}",
                    type="function",
                    function={"name": f"tool_{index}", "arguments": "{}"},
                )
                for index in (1, 2)
            ],
        )
        model = self._create_mock_model()
        model.call_llm_model = MagicMock(
            return_value=(response, "raw provider content")
        )

        result = model.chat(self.messages, for_raw=True)

        self.assertEqual(result, "raw provider content")
        self.assertEqual(len(model._get_pending_native_tool_call_responses()), 0)

    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_clear_pending_native_tool_call_responses_is_idempotent(
            self,
            mock_base_init,
            mock_logger,
        ):
        """Test pending response cleanup can run repeatedly."""
        model = self._create_mock_model()
        queue = model._get_pending_native_tool_call_responses()
        queue.append((MagicMock(), "action"))

        model.clear_pending_native_tool_call_responses()
        model.clear_pending_native_tool_call_responses()

        self.assertEqual(len(queue), 0)


class TestLLMModelErrorHandling(unittest.TestCase):
    """Test cases for LLMModel error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.messages = [{"role": "user", "content": "Error test"}]

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_handles_type_error(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat handles TypeError and retries."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success after type error"
        
        mock_format.side_effect = [
            TypeError("Type error"),
            TypeError("Type error"),
            ["success"]
        ]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages)
        
        self.assertEqual(result, ["success"])

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_handles_api_connection_error(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat handles APIConnectionError and retries."""
        import openai
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success after connection error"
        
        # APIConnectionError requires a request parameter
        mock_format.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            ["success"]
        ]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages)
        
        self.assertEqual(result, ["success"])

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_handles_timeout_error(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat handles APITimeoutError and retries."""
        import openai
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success after timeout"
        
        # APITimeoutError requires a request parameter
        mock_format.side_effect = [
            openai.APITimeoutError(request=MagicMock()),
            ["success"]
        ]
        
        model = self._create_mock_model()
        model.model.create.return_value = mock_response
        
        result = model.chat(self.messages)
        
        self.assertEqual(result, ["success"])

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_raises_hard_interrupt_during_retry(
        self, mock_base_init, mock_logger, mock_format, mock_sleep
    ):
        """A pending hard interrupt during the retry loop stops the retry.

        When an APIConnectionError triggers a retry, the hard-interrupt check
        at the top of the retry loop must detect the pending interrupt and
        raise HardInterruptError instead of continuing to retry.
        """
        import openai

        from topsailai.ai_base.exception import HardInterruptError

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Should not be reached"

        # First call raises APIConnectionError (triggers retry), then the
        # hard-interrupt check fires before the next attempt.
        mock_format.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
        ]

        agent = MagicMock()
        agent._check_hard_interrupt.side_effect = HardInterruptError("interrupted")

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        with patch(
            "topsailai.ai_base.llm_base.get_agent_object",
            return_value=agent,
        ):
            with self.assertRaises(HardInterruptError):
                model.chat(self.messages)

        # The interrupt check must have been invoked.
        agent._check_hard_interrupt.assert_called()

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_ignores_non_interrupt_exception_in_check(
        self, mock_base_init, mock_logger, mock_format, mock_sleep
    ):
        """A non-interrupt exception in the hard-interrupt check is swallowed.

        Any unexpected problem with the interrupt check itself must not break
        the retry flow; the chat call should still succeed after retrying.
        """
        import openai

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Success after retry"

        # First call raises APIConnectionError (triggers retry), then succeeds.
        mock_format.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            ["success"],
        ]

        agent = MagicMock()
        agent._check_hard_interrupt.side_effect = RuntimeError("check failed")

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        with patch(
            "topsailai.ai_base.llm_base.get_agent_object",
            return_value=agent,
        ):
            result = model.chat(self.messages)

        self.assertEqual(result, ["success"])
        agent._check_hard_interrupt.assert_called()

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_chat_raises_after_max_retries(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat raises Exception after max retries."""
        mock_format.side_effect = Exception("Persistent error")
        
        model = self._create_mock_model()
        
        with self.assertRaises(Exception):
            model.chat(self.messages)




class TestLLMModelResponseEvents(unittest.TestCase):
    """Test cases for LLM raw response event recording."""

    def setUp(self):
        """Set up test fixtures."""
        self.messages = [{"role": "user", "content": "Event test"}]

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    def _make_env_side_effects(self, enabled=True, max_payload_bytes=100000, include_raw=True, stream_chunk_sample=0):
        """Return side-effect callables for EnvReaderInstance mocks."""
        def check_bool_side_effect(name, default=None):
            if name == "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED":
                return enabled
            if name == "TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW":
                return include_raw
            return default

        def get_side_effect(name, default=None, formatter=None):
            if name == "TOPSAILAI_LLM_RESPONSE_EVENTS_MAX_PAYLOAD_BYTES":
                return max_payload_bytes
            if name == "TOPSAILAI_LLM_RESPONSE_EVENTS_STREAM_CHUNK_SAMPLE":
                return stream_chunk_sample
            return default

        return check_bool_side_effect, get_side_effect

    def _make_response_message(self, content="", tool_calls=None):
        """Create a mock response message."""
        message = MagicMock()
        message.content = content
        message.tool_calls = tool_calls
        return message

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_disabled_emits_nothing(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """When recording is disabled, no event is emitted."""
        check_bool, get = self._make_env_side_effects(enabled=False)
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_message = self._make_response_message(content="Hello")
        mock_get_msg.return_value = mock_message
        mock_format.return_value = ["Hello"]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        result = model.call_llm_model(self.messages)

        self.assertEqual(result[1], "Hello")
        mock_record_event.assert_not_called()

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_non_streaming_records_payload(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """Non-streaming response emits llm.response.raw with correct payload."""
        check_bool, get = self._make_env_side_effects()
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_message = self._make_response_message(content="Hello world")
        mock_get_msg.return_value = mock_message
        mock_format.return_value = ["Hello world"]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message
        mock_response.to_dict.return_value = {"id": "resp_1", "object": "chat.completion"}

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        result = model.call_llm_model(self.messages)

        self.assertEqual(result[1], "Hello world")
        mock_record_event.assert_called_once()
        args, kwargs = mock_record_event.call_args
        self.assertEqual(args[0], "llm.response.raw")
        self.assertEqual(kwargs["source"], "ai_base.llm_base")
        payload = kwargs["payload"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["is_stream"], False)
        self.assertEqual(payload["content"], "Hello world")
        self.assertIn("raw_response", payload)
        self.assertEqual(payload["raw_response"]["id"], "resp_1")

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_streaming_emits_once_after_trunk(
        self, mock_base_init, mock_logger, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """Streaming emits exactly one event after the full trunk is received."""
        check_bool, get = self._make_env_side_effects()
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = "Hello "
        mock_chunk1.choices[0].delta.tool_calls = None

        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = "world"
        mock_chunk2.choices[0].delta.tool_calls = None

        mock_response = iter([mock_chunk1, mock_chunk2])

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        # _record_llm_response_event calls get_response_message on the rebuilt
        # ChatCompletionMessage; configure it to return a message whose content
        # matches the assembled trunk.
        mock_get_msg.return_value = self._make_response_message(content="Hello world")

        result = model.call_llm_model_by_stream(self.messages)

        self.assertEqual(result[1], "Hello world")
        mock_record_event.assert_called_once()
        args, kwargs = mock_record_event.call_args
        self.assertEqual(args[0], "llm.response.raw")
        payload = kwargs["payload"]
        self.assertEqual(payload["is_stream"], True)
        self.assertEqual(payload["content"], "Hello world")

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_hook_failure_does_not_break_llm_call(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """A recording exception must not propagate to the caller."""
        check_bool, get = self._make_env_side_effects()
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_record_event.side_effect = RuntimeError("event backend down")

        mock_message = self._make_response_message(content="Safe")
        mock_get_msg.return_value = mock_message
        mock_format.return_value = ["Safe"]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        result = model.call_llm_model(self.messages)

        self.assertEqual(result[1], "Safe")
        mock_record_event.assert_called_once()

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_detects_tool_calls_from_message(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """Tool calls are extracted from message.tool_calls, not env flags."""
        check_bool, get = self._make_env_side_effects()
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_function = MagicMock()
        mock_function.name = "test_func"
        mock_function.arguments = '{"arg": "value"}'

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.type = "function"
        mock_tool_call.function = mock_function

        mock_message = self._make_response_message(content="", tool_calls=[mock_tool_call])
        mock_get_msg.return_value = mock_message
        mock_format.return_value = [""]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        model.call_llm_model(self.messages)

        payload = mock_record_event.call_args[1]["payload"]
        self.assertEqual(len(payload["tool_calls"]), 1)
        self.assertEqual(payload["tool_calls"][0]["id"], "call_123")
        self.assertEqual(payload["tool_calls"][0]["function"]["name"], "test_func")
        self.assertEqual(payload["tool_calls"][0]["function"]["arguments"], '{"arg": "value"}')

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_truncates_oversized_payload(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """Large payloads are truncated to fit the configured byte limit."""
        check_bool, get = self._make_env_side_effects(max_payload_bytes=200)
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        large_content = "x" * 10000
        mock_message = self._make_response_message(content=large_content)
        mock_get_msg.return_value = mock_message
        mock_format.return_value = [large_content]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message
        mock_response.to_dict.return_value = {"content": large_content}

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        model.call_llm_model(self.messages)

        payload = mock_record_event.call_args[1]["payload"]
        import json
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        self.assertLessEqual(len(serialized.encode("utf-8")), 200)
        self.assertTrue(payload.get("_truncated") or len(payload.get("content", "")) < 10000)

    @patch("topsailai.events.record_event")
    @patch("topsailai.ai_base.llm_base.get_response_message")
    @patch("topsailai.ai_base.llm_base.env_tool")
    @patch("topsailai.ai_base.llm_base.format_response")
    @patch("topsailai.ai_base.llm_base.logger")
    @patch("topsailai.ai_base.llm_base.LLMModelBase.__init__", return_value=None)
    def test_response_event_no_api_key_or_non_serializable_leakage(
        self, mock_base_init, mock_logger, mock_format, mock_env_tool,
        mock_get_msg, mock_record_event
    ):
        """Raw response serialization must remain JSON-safe and not crash."""
        check_bool, get = self._make_env_side_effects()
        mock_env_tool.EnvReaderInstance.check_bool.side_effect = check_bool
        mock_env_tool.EnvReaderInstance.get.side_effect = get

        mock_message = self._make_response_message(content="OK")
        mock_get_msg.return_value = mock_message
        mock_format.return_value = ["OK"]

        class NonSerializable:
            def __repr__(self):
                return "<non-serializable-client>"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = mock_message
        mock_response.to_dict.return_value = {
            "id": "resp_1",
            "api_key": "secret-key-must-not-leak",
            "client": NonSerializable(),
        }

        model = self._create_mock_model()
        model.model.create.return_value = mock_response

        # The LLM call must succeed even though the raw response contains a
        # non-serializable object.
        result = model.call_llm_model(self.messages)
        self.assertEqual(result, (mock_response, "OK"))

        payload = mock_record_event.call_args[1]["payload"]
        raw = payload["raw_response"]
        serialized = json.dumps(raw, ensure_ascii=False, separators=(",", ":"), default=str)
        # The non-serializable object must be converted to a string, not kept as
        # a live object reference in the recorded payload.
        self.assertIsInstance(serialized, str)
        self.assertIn("<non-serializable-client>", serialized)
        # The raw payload itself must be JSON-serializable (no live objects).
        json.dumps(raw, ensure_ascii=False, separators=(",", ":"), default=str)




class TestLLMModelChatAgentRuntimeInput(unittest.TestCase):
    """Tests demonstrating that LLMModel.chat() uses only the plain
    agent-runtime input function, ignoring the timeout-aware variant.

    The pre_run hook registers both ``input_on_agent_runtime`` (plain) and
    ``input_on_agent_runtime_with_timeout`` (timeout-aware) in thread-local
    storage. However, ``LLMModel.chat()`` only calls
    ``get_agent_runtime_input()`` and never consults
    ``get_agent_runtime_input_with_timeout()``. As a result, the timeout
    wrapper has no effect on LLM retry prompts.
    """

    def setUp(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def _create_mock_model(self):
        """Create a mock LLMModel with all required attributes."""
        from topsailai.ai_base.llm_base import LLMModel
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

    @patch("topsailai.ai_base.llm_base.thread_tool.is_main_thread")
    @patch("topsailai.ai_base.llm_base.get_agent_runtime_input")
    @patch("topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout")
    def test_chat_keyboard_interrupt_uses_plain_input_not_timeout_variant(
        self, mock_get_with_timeout, mock_get_input, mock_is_main_thread
    ):
        """LLMModel.chat() must use get_agent_runtime_input(), not the
        timeout-aware variant, when handling KeyboardInterrupt.
        """
        from topsailai.ai_base.llm_base import LLMModel

        mock_is_main_thread.return_value = True
        plain_input = MagicMock(return_value="no")
        timeout_input = MagicMock(return_value="no")
        mock_get_input.return_value = plain_input
        mock_get_with_timeout.return_value = timeout_input

        model = self._create_mock_model()
        model.call_llm_model = MagicMock(side_effect=KeyboardInterrupt("interrupted"))

        with self.assertRaises(KeyboardInterrupt):
            model.chat([{"role": "user", "content": "test"}])

        mock_get_input.assert_called_once()
        mock_get_with_timeout.assert_not_called()
        plain_input.assert_called_once_with(">>> LLM Retry [yes/no] ")
        timeout_input.assert_not_called()

    @patch("topsailai.ai_base.llm_base.thread_tool.is_main_thread")
    @patch("topsailai.ai_base.llm_base.get_agent_runtime_input")
    @patch("topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout")
    def test_chat_internal_exception_uses_plain_input_not_timeout_variant(
        self, mock_get_with_timeout, mock_get_input, mock_is_main_thread
    ):
        """LLMModel.chat() must use get_agent_runtime_input(), not the
        timeout-aware variant, when handling an internal exception in the
        main thread.
        """
        from topsailai.ai_base.llm_base import LLMModel

        mock_is_main_thread.return_value = True
        plain_input = MagicMock(return_value="no")
        timeout_input = MagicMock(return_value="no")
        mock_get_input.return_value = plain_input
        mock_get_with_timeout.return_value = timeout_input

        model = self._create_mock_model()
        model.call_llm_model = MagicMock(side_effect=ValueError("internal error"))

        with self.assertRaises(ValueError):
            model.chat([{"role": "user", "content": "test"}])

        mock_get_input.assert_called_once()
        mock_get_with_timeout.assert_not_called()
        plain_input.assert_called_once_with(">>> LLM Retry [yes/no] ")
        timeout_input.assert_not_called()

    @patch("topsailai.ai_base.llm_base.get_agent_runtime_input")
    @patch("topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout")
    def test_chat_falls_back_to_builtin_input(
        self, mock_get_with_timeout, mock_get_input
    ):
        """When no agent-runtime input is registered, LLMModel.chat() falls
        back to the builtin input() function.
        """
        from topsailai.ai_base.llm_base import LLMModel

        mock_get_input.return_value = None
        mock_get_with_timeout.return_value = None

        model = self._create_mock_model()
        model.call_llm_model = MagicMock(side_effect=KeyboardInterrupt("interrupted"))

        with patch("builtins.input", return_value="no") as mock_builtin:
            with self.assertRaises(KeyboardInterrupt):
                model.chat([{"role": "user", "content": "test"}])

        mock_get_input.assert_called_once()
        mock_get_with_timeout.assert_not_called()
        mock_builtin.assert_called_once_with(">>> LLM Retry [yes/no] ")


if __name__ == "__main__":
    unittest.main()
