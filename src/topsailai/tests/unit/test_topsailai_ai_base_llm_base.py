"""
Unit tests for ai_base/llm_base.py module.

This module contains unit tests for the LLMModel class which provides
OpenAI-compatible LLM interaction capabilities.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestLLMModelGetModelName(unittest.TestCase):
    """Test cases for LLMModel.get_model_name method."""

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
    def test_chat_raises_after_max_retries(self, mock_base_init, mock_logger, mock_format, mock_sleep):
        """Test chat raises Exception after max retries."""
        mock_format.side_effect = Exception("Persistent error")
        
        model = self._create_mock_model()
        
        with self.assertRaises(Exception):
            model.chat(self.messages)


if __name__ == "__main__":
    unittest.main()
