"""
Unit tests for ai_base/llm_base module.

Test coverage:
- LLMModel class initialization
- Model name retrieval
- LLM model creation
- Response message extraction
- Chat method with various parameters

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestLLMModelImports(unittest.TestCase):
    """Test cases for module imports."""

    def test_import_llm_model(self):
        """Test LLMModel can be imported."""
        from topsailai.ai_base.llm_base import LLMModel
        self.assertTrue(callable(LLMModel))

    def test_import_role_assistant(self):
        """Test ROLE_ASSISTANT constant can be imported."""
        from topsailai.ai_base.llm_base import ROLE_ASSISTANT
        self.assertEqual(ROLE_ASSISTANT, "assistant")


class TestLLMModelInit(unittest.TestCase):
    """Test cases for LLMModel initialization."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_init_with_default_params(self):
        """Test LLMModel initializes with default parameters."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertIsNotNone(model)

    def test_init_with_model_name(self):
        """Test LLMModel initializes with provided model_name."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel(model_name="test-model")
        self.assertIsNotNone(model)


class TestLLMModelGetModelName(unittest.TestCase):
    """Test cases for LLMModel get_model_name method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_get_model_name_method_exists(self):
        """Test LLMModel has get_model_name method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "get_model_name"))
        self.assertTrue(callable(model.get_model_name))

    def test_get_model_name_returns_str(self):
        """Test get_model_name returns a string."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        result = model.get_model_name()
        self.assertIsInstance(result, str)

    def test_get_model_name_default_value(self):
        """Test get_model_name returns default value when env var not set."""
        from topsailai.ai_base.llm_base import LLMModel
        
        # Ensure env var is not set
        os.environ.pop("OPENAI_MODEL", None)
        
        model = LLMModel()
        result = model.get_model_name()
        self.assertEqual(result, "DeepSeek-V3.1-Terminus")

    def test_get_model_name_from_env(self):
        """Test get_model_name returns value from OPENAI_MODEL env var."""
        from topsailai.ai_base.llm_base import LLMModel
        
        os.environ["OPENAI_MODEL"] = "custom-model"
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]
        
        model = LLMModel()
        result = model.get_model_name()
        self.assertEqual(result, "custom-model")


class TestLLMModelGetLLMModel(unittest.TestCase):
    """Test cases for LLMModel get_llm_model method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_get_llm_model_method_exists(self):
        """Test LLMModel has get_llm_model method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "get_llm_model"))
        self.assertTrue(callable(model.get_llm_model))


class TestLLMModelGetResponseMessage(unittest.TestCase):
    """Test cases for LLMModel get_response_message method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_get_response_message_method_exists(self):
        """Test LLMModel has get_response_message method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "get_response_message"))
        self.assertTrue(callable(model.get_response_message))


class TestLLMModelCallLLMModel(unittest.TestCase):
    """Test cases for LLMModel call_llm_model method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_call_llm_model_method_exists(self):
        """Test LLMModel has call_llm_model method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "call_llm_model"))
        self.assertTrue(callable(model.call_llm_model))


class TestLLMModelCallLLMModelByStream(unittest.TestCase):
    """Test cases for LLMModel call_llm_model_by_stream method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_call_llm_model_by_stream_method_exists(self):
        """Test LLMModel has call_llm_model_by_stream method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "call_llm_model_by_stream"))
        self.assertTrue(callable(model.call_llm_model_by_stream))


class TestLLMModelChat(unittest.TestCase):
    """Test cases for LLMModel chat method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_chat_method_exists(self):
        """Test LLMModel has chat method."""
        from topsailai.ai_base.llm_base import LLMModel
        
        model = LLMModel()
        self.assertTrue(hasattr(model, "chat"))
        self.assertTrue(callable(model.chat))


class TestLLMModelInheritance(unittest.TestCase):
    """Test cases for LLMModel inheritance."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_inherits_from_llm_model_base(self):
        """Test LLMModel inherits from LLMModelBase."""
        from topsailai.ai_base.llm_base import LLMModel
        from topsailai.ai_base.llm_control.base_class import LLMModelBase
        
        self.assertTrue(issubclass(LLMModel, LLMModelBase))


if __name__ == "__main__":
    unittest.main()
