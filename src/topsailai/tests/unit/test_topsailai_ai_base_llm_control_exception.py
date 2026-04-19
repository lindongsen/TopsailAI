"""
Test module for ai_base/llm_control/exception.py

Author: AI
Purpose: Unit tests for exception classes
"""

import pytest


class TestJsonError:
    """Test suite for JsonError exception class."""

    def test_json_error_is_exception(self):
        """Verify JsonError is a subclass of Exception."""
        from topsailai.ai_base.llm_control.exception import JsonError

        assert issubclass(JsonError, Exception)

    def test_json_error_can_be_raised(self):
        """Verify JsonError can be raised and caught."""
        from topsailai.ai_base.llm_control.exception import JsonError

        with pytest.raises(JsonError):
            raise JsonError("invalid json string")

    def test_json_error_message(self):
        """Verify JsonError preserves the error message."""
        from topsailai.ai_base.llm_control.exception import JsonError

        msg = "test error message"
        with pytest.raises(JsonError) as exc_info:
            raise JsonError(msg)

        assert str(exc_info.value) == msg

    def test_json_error_empty_message(self):
        """Verify JsonError works with empty message."""
        from topsailai.ai_base.llm_control.exception import JsonError

        with pytest.raises(JsonError) as exc_info:
            raise JsonError()

        assert str(exc_info.value) == ""


class TestModelServiceError:
    """Test suite for ModelServiceError exception class."""

    def test_model_service_error_is_exception(self):
        """Verify ModelServiceError is a subclass of Exception."""
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        assert issubclass(ModelServiceError, Exception)

    def test_model_service_error_can_be_raised(self):
        """Verify ModelServiceError can be raised and caught."""
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        with pytest.raises(ModelServiceError):
            raise ModelServiceError()

    def test_model_service_error_message(self):
        """Verify ModelServiceError preserves the error message."""
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        msg = "model service error"
        with pytest.raises(ModelServiceError) as exc_info:
            raise ModelServiceError(msg)

        assert str(exc_info.value) == msg

    def test_model_service_error_with_dict(self):
        """Verify ModelServiceError works with dict message."""
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        msg = {"status": 500, "message": "error"}
        with pytest.raises(ModelServiceError) as exc_info:
            raise ModelServiceError(msg)

        assert str(exc_info.value) == str(msg)


class TestExceptionInheritance:
    """Test suite for exception class inheritance."""

    def test_json_error_not_model_service_error(self):
        """Verify JsonError is not a ModelServiceError."""
        from topsailai.ai_base.llm_control.exception import JsonError, ModelServiceError

        assert not issubclass(JsonError, ModelServiceError)

    def test_model_service_error_not_json_error(self):
        """Verify ModelServiceError is not a JsonError."""
        from topsailai.ai_base.llm_control.exception import JsonError, ModelServiceError

        assert not issubclass(ModelServiceError, JsonError)

    def test_json_error_caught_correctly(self):
        """Verify JsonError can be caught by itself."""
        from topsailai.ai_base.llm_control.exception import JsonError

        caught = False
        try:
            raise JsonError("json error")
        except JsonError:
            caught = True

        assert caught is True

    def test_model_service_error_caught_correctly(self):
        """Verify ModelServiceError can be caught by itself."""
        from topsailai.ai_base.llm_control.exception import ModelServiceError

        caught = False
        try:
            raise ModelServiceError("model error")
        except ModelServiceError:
            caught = True

        assert caught is True
