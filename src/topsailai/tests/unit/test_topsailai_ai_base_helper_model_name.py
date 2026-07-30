"""
Author: DawsonLin
Unit tests for topsailai.ai_base.helper.model_name.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

from topsailai.ai_base.helper.model_name import get_current_model_name


def _make_agent(model_name: str):
    """Create an agent with the requested runtime model name."""
    return SimpleNamespace(llm_model=SimpleNamespace(model_name=model_name))


def _make_response(model_name: str):
    """Create a response with the requested model name."""
    return SimpleNamespace(model=model_name)


def test_get_current_model_name_prefers_runtime_agent():
    """Prefer the runtime agent when every model source is available."""
    agent = _make_agent("runtime-model")
    response = _make_response("response-model")

    with patch(
        "topsailai.ai_base.helper.model_name.get_agent_object",
        return_value=agent,
    ), patch.dict(os.environ, {"OPENAI_MODEL": "environment-model"}, clear=True):
        assert get_current_model_name(response) == "runtime-model"


def test_get_current_model_name_falls_back_to_response():
    """Prefer the response when runtime agent information is unavailable."""
    response = _make_response("response-model")

    with patch(
        "topsailai.ai_base.helper.model_name.get_agent_object",
        return_value=None,
    ), patch.dict(os.environ, {"OPENAI_MODEL": "environment-model"}, clear=True):
        assert get_current_model_name(response) == "response-model"


def test_get_current_model_name_falls_back_to_environment():
    """Use the environment when runtime and response sources are unavailable."""
    with patch(
        "topsailai.ai_base.helper.model_name.get_agent_object",
        return_value=None,
    ), patch.dict(os.environ, {"OPENAI_MODEL": "environment-model"}, clear=True):
        assert get_current_model_name() == "environment-model"


def test_get_current_model_name_defaults_to_empty_string():
    """Return an empty string when every model source is unavailable."""
    with patch(
        "topsailai.ai_base.helper.model_name.get_agent_object",
        return_value=None,
    ), patch.dict(os.environ, {}, clear=True):
        assert get_current_model_name() == ""
