"""Unique BDD steps for session metadata model-name projection."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, then, when

from topsailai.utils.instruction_tool import HookInstruction
from topsailai.workspace import session_meta
from topsailai.workspace.plugin_instruction import agent as agent_instruction
from topsailai.workspace.plugin_instruction.base import cache as instruction_cache


class _FakeLLMModel:
    """Expose only the fields a model-only switch reads and writes."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model_config = {"api_key": "", "api_base": ""}
        self.model = None
        self.models = []


class _FakeRuntime:
    """Hold the LLM model the instruction mutates."""

    def __init__(self, model_name: str) -> None:
        self.llm_model = _FakeLLMModel(model_name)


class _FakeAgent:
    """Provide the agent surface the metadata writer and instruction read."""

    def __init__(self, model_name: str) -> None:
        self.agent_name = "BddAgent"
        self.agent_type = "react"
        self.agent_role = "worker"
        self.llm_model = _FakeLLMModel(model_name)
        self.runtime = _FakeRuntime(model_name)


@pytest.fixture
def session_meta_model_ctx():
    """Store the isolated instruction scenario state."""
    return {}


@given("an isolated session metadata file created for the current process")
def given_isolated_session_metadata(session_meta_model_ctx, bdd_tmp_path):
    """Create a real metadata file and a real model registry in owned storage."""
    scenario_dir = Path(bdd_tmp_path)
    task_dir = scenario_dir / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    registry_file = scenario_dir / ".models.jsonl"
    registry_file.write_text(
        json.dumps({"name": "ModelA"}) + "\n",
        encoding="utf-8",
    )

    original_task_folder = session_meta.FOLDER_WORKSPACE_TASK
    original_registry_file = agent_instruction.FILE_MODELS_REGISTRY
    original_agent = instruction_cache.g_ai_agent
    exported_keys = ("OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_API_KEY")
    original_exported = {key: os.environ.get(key) for key in exported_keys}
    session_meta.FOLDER_WORKSPACE_TASK = str(task_dir)
    agent_instruction.FILE_MODELS_REGISTRY = str(registry_file)

    agent = _FakeAgent("OldModel")
    instruction_cache.set_ai_agent(agent)
    session_id = "bdd-meta-model"
    with patch.dict(os.environ, {"SESSION_ID": session_id}):
        meta_path = session_meta.create_session_meta(session_id, agent)
    assert meta_path is not None
    created = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    assert created["model_name"] == "OldModel"

    session_meta_model_ctx.update(
        agent=agent,
        session_id=session_id,
        meta_path=meta_path,
        completions_file=str(scenario_dir / "completions.json"),
    )
    try:
        yield session_meta_model_ctx
    finally:
        session_meta.FOLDER_WORKSPACE_TASK = original_task_folder
        agent_instruction.FILE_MODELS_REGISTRY = original_registry_file
        instruction_cache.g_ai_agent = original_agent
        for key, value in original_exported.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@when("the operator selects a registered model through the instruction")
def when_operator_selects_registered_model(session_meta_model_ctx):
    """Invoke the real slash instruction over the real registry and metadata."""
    hook = HookInstruction(
        file_input_completions=session_meta_model_ctx["completions_file"],
        instructions=agent_instruction.INSTRUCTIONS,
    )
    with patch.dict(os.environ, {"SESSION_ID": session_meta_model_ctx["session_id"]}):
        session_meta_model_ctx["report"] = hook.call_instruction("/models", "ModelA")


@then("the metadata file records the newly applied model name")
def then_metadata_records_applied_model(session_meta_model_ctx):
    """Assert the on-disk metadata follows the applied model."""
    meta = json.loads(
        Path(session_meta_model_ctx["meta_path"]).read_text(encoding="utf-8")
    )
    assert meta["model_name"] == "ModelA"
    assert session_meta_model_ctx["agent"].runtime.llm_model.model_name == "ModelA"


@then("the instruction reports the previous and applied model names")
def then_instruction_reports_both_names(session_meta_model_ctx):
    """Assert the operator sees the transition that was projected."""
    report = session_meta_model_ctx["report"]
    assert "model_name: OldModel -> ModelA" in report
