'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

import os

from topsailai.utils import (
    env_tool,
    json_tool,
)
from topsailai.utils.print_tool import print_info, print_warning
from topsailai.tools.base.common import get_tools_for_chat
from topsailai.prompt_hub.prompt_tool import get_observation_by_tools
from topsailai.workspace.folder_constants import FOLDER_ROOT
from topsailai.workspace.plugin_instruction.base.cache import get_ai_agent

# Path to the user-defined model registry (JSON Lines).
FILE_MODELS_REGISTRY = os.path.join(FOLDER_ROOT, ".models.jsonl")


def _load_models_registry() -> dict:
    """
    Load the user-defined model registry from ${TOPSAILAI_HOME}/.models.jsonl.

    Returns:
        dict: Mapping from model name to model configuration dict.
    """
    registry = {}
    if not os.path.exists(FILE_MODELS_REGISTRY):
        return registry

    try:
        with open(FILE_MODELS_REGISTRY, encoding="utf-8") as fd:
            for line in fd:
                line = line.strip()
                if not line:
                    continue
                try:
                    config = json_tool.safe_json_load(line)
                except Exception:
                    print_warning(f"Invalid JSON line in {FILE_MODELS_REGISTRY}: {line}")
                    continue
                if not isinstance(config, dict):
                    continue
                name = config.get("name")
                if not name:
                    continue
                registry[name] = config
    except Exception as e:
        print_warning(f"Failed to load models registry from {FILE_MODELS_REGISTRY}: {e}")

    return registry


def _apply_model_config(agent, config: dict) -> str:
    """
    Apply a model configuration to the active agent and process environment.

    Args:
        agent: The current agent instance.
        config (dict): Model configuration containing model, endpoint, credentials, and environment.

    Returns:
        str: Human-readable summary of the applied changes.
    """
    llm_model = agent.llm_model
    old_model_name = llm_model.model_name
    old_api_base = getattr(llm_model.model_config, "api_base", "") or llm_model.model_config.get("api_base", "")
    old_api_key = getattr(llm_model.model_config, "api_key", "") or llm_model.model_config.get("api_key", "")

    new_model_name = config.get("model_name") or config.get("model") or config.get("name") or old_model_name
    new_api_base = config.get("api_base") or config.get("base_url") or old_api_base
    api_key_env = config.get("api_key_env")
    configured_api_key = os.getenv(api_key_env) if api_key_env else config.get("api_key")
    new_api_key = configured_api_key if configured_api_key is not None else old_api_key

    llm_model.model_name = new_model_name

    # Rebuild the client when endpoint credentials change so the next LLM call
    # uses the new configuration. Clear the failover model pool to prevent
    # LLMModelBase.chat_model from randomly selecting an old endpoint.
    if new_api_base != old_api_base or new_api_key != old_api_key:
        llm_model.model = llm_model.get_llm_model(
            api_key=new_api_key,
            api_base=new_api_base,
        )
        llm_model.model_config = {"api_key": new_api_key, "api_base": new_api_base}
        llm_model.models = []

    environment = config.get("environment")
    if isinstance(environment, dict):
        for env_name, env_value in environment.items():
            os.environ[env_name] = str(env_value)
            print_info(f"Set environment variable: {env_name}={env_value}")

    # Keep process-level OpenAI-compatible settings aligned with the selected
    # model so later clients and model-dependent hooks observe the same provider.
    os.environ["OPENAI_MODEL"] = str(new_model_name)
    if new_api_base:
        os.environ["OPENAI_BASE_URL"] = str(new_api_base)
        os.environ["OPENAI_API_BASE"] = str(new_api_base)
    if new_api_key:
        os.environ["OPENAI_API_KEY"] = str(new_api_key)

    credential_mappings = (
        (config.get("organization_env"), "OPENAI_ORG_ID"),
        (config.get("project_env"), "OPENAI_PROJECT_ID"),
    )
    for source_name, target_name in credential_mappings:
        if source_name and os.getenv(source_name) is not None:
            os.environ[target_name] = os.environ[source_name]

    result = (
        f"model_name: {old_model_name} -> {new_model_name}, "
        f"api_base: {old_api_base} -> {new_api_base}"
    )
    return result


def get_system_prompt() -> str:
    """
    Print system prompt
    """
    agent = get_ai_agent()
    if agent:
        print(agent.messages[0]["content"])
    return

def get_env_prompt() -> str:
    """
    Print env prompt
    """
    agent = get_ai_agent()
    if agent:
        print(agent.messages[1]["content"])
    return

def get_tool_prompt() -> str:
    """
    Print tool prompt
    """
    agent = get_ai_agent()
    if agent:
        if env_tool.is_use_tool_calls():
            content = get_tools_for_chat(agent.available_tools)
            content = json_tool.safe_json_dump(content, indent=2)
            print(content)
            print("\n---\n")
        print(agent.messages[2]["content"])

    return

def get_messages() -> str:
    """
    Print current messages
    """
    agent = get_ai_agent()
    if agent:
        return json_tool.json_dump(agent.messages) + f"\n\n---\n\nTotalCount: {len(agent.messages)}\n"
    return

def get_tools() -> list[str]:
    """
    Print tools
    """
    agent = get_ai_agent()
    if agent:
        print(sorted(list(agent.available_tools.keys())))
    return


def get_tools_observation() -> str:
    """Return observations exposed by the active agent's tool modules."""
    agent = get_ai_agent()
    if not agent:
        return

    tool_names = sorted(agent.available_tools.keys())
    return get_observation_by_tools(tool_names)

def set_llm(*args) -> str:
    """
    Change LLM configuration for the active agent.

    Supported forms:
      /set_llm <model_name>
      /set_llm model=<model_name>
      /set_llm model=<model_name> base_url=<api_base> api_key=<api_key>
      /set_llm model=<model_name> api_key_env=MY_API_KEY

    Args:
        *args: Positional arguments from the instruction parser.
    """
    agent = get_ai_agent()
    if not agent:
        return "No active agent"

    if not args:
        return f"Current model: {agent.llm_model.model_name}"

    config = {}

    # Single positional argument: treat as model name.
    if len(args) == 1 and "=" not in str(args[0]):
        config["model_name"] = args[0]
    else:
        # Parse key=value pairs.
        for arg in args:
            arg = str(arg)
            if "=" not in arg:
                continue
            key, value = arg.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in ("model", "model_name"):
                config["model_name"] = value
            elif key in ("base_url", "api_base"):
                config["api_base"] = value
            elif key == "api_key":
                config["api_key"] = value
            elif key == "api_key_env":
                config["api_key"] = os.getenv(value, "")

    if not config:
        return f"Current model: {agent.llm_model.model_name}"

    result = _apply_model_config(agent, config)
    return result


def get_llm() -> str:
    """
    Print LLM name
    """
    agent = get_ai_agent()
    if not agent:
        return

    llm = agent.llm_model.model_name
    return llm


def select_model(*args) -> str:
    """
    List or select a model from the user-defined model registry.

    Supported forms:
      /models              # list available models
      /models <model_name> # select and apply the named model
      /models <number>     # select and apply the model by 1-based index

    Args:
        *args: Positional arguments from the instruction parser.
    """
    agent = get_ai_agent()
    if not agent:
        return "No active agent"

    registry = _load_models_registry()
    current_model = agent.llm_model.model_name
    model_names = sorted(registry.keys())

    if not args:
        if not registry:
            return f"Current model: {current_model}\nNo models found in {FILE_MODELS_REGISTRY}"

        lines = []
        if current_model not in registry:
            lines.append(f"Current model: {current_model} (not in registry)")
        lines.append("Available models:")
        for idx, name in enumerate(model_names, start=1):
            config = registry[name]
            api_base = config.get("api_base") or config.get("base_url", "")
            marker = "* " if name == current_model else ""
            lines.append(f"  {idx}. {marker}{name} ({api_base})")
        return "\n".join(lines)

    arg = str(args[0]).strip()
    # Numeric 1-based index selection.
    if arg.isdigit():
        index = int(arg)
        if index < 1 or index > len(model_names):
            return f"Invalid model index: {index}. Valid range: 1-{len(model_names)}"
        model_name = model_names[index - 1]
    else:
        model_name = arg

    config = registry.get(model_name)
    if not config:
        return f"Model not found: {model_name}"

    result = _apply_model_config(agent, config)
    return result


def _format_estimated_tokens(token_count: int | None) -> str:
    """Format an estimated token count for human-readable output."""
    if token_count is None:
        return "unavailable"
    return f"{token_count:,}"


def get_tokens(ctx_runtime_data=None) -> str:
    """Report real-time token estimates for Agent2LLM and User2Agent messages."""
    agent = getattr(ctx_runtime_data, "ai_agent", None) or get_ai_agent()
    if not agent:
        return "No active agent"

    agent_messages = getattr(agent, "messages", None)
    agent2llm_messages = list(agent_messages) if agent_messages is not None else []
    user2agent_messages = None
    session_id = ""
    if ctx_runtime_data is not None:
        runtime_messages = getattr(ctx_runtime_data, "messages", None)
        user2agent_messages = list(runtime_messages) if runtime_messages is not None else []
        session_id = getattr(ctx_runtime_data, "session_id", "") or ""

    agent2llm_tokens = None
    user2agent_tokens = None
    if ctx_runtime_data is not None:
        agent2llm_tokens = ctx_runtime_data._get_current_tokens(agent2llm_messages)
        if user2agent_messages is not None:
            user2agent_tokens = ctx_runtime_data._get_current_tokens(user2agent_messages)

    llm_model = getattr(agent, "llm_model", None)
    model_name = getattr(llm_model, "model_name", "") or "unavailable"
    completion_reserve = getattr(llm_model, "max_tokens", 0) or 0

    lines = [
        f"Model: {model_name}",
        "",
        "Agent2LLM:",
        f"  Messages: {len(agent2llm_messages)}",
        f"  Estimated tokens: {_format_estimated_tokens(agent2llm_tokens)}",
        "",
        "User2Agent:" + (" (ephemeral/unsaved session)" if not session_id else ""),
        f"  Messages: {len(user2agent_messages) if user2agent_messages is not None else 0}",
        f"  Estimated tokens: {_format_estimated_tokens(user2agent_tokens)}",
        "",
        "Context:",
    ]

    watermark = None
    if ctx_runtime_data is not None and agent2llm_tokens is not None:
        watermark = ctx_runtime_data._classify_context_watermark(
            current_tokens=agent2llm_tokens,
            model_name=model_name,
            max_tokens=completion_reserve,
        )
    if watermark is None:
        lines.append("  Model maximum: unavailable")
        return "\n".join(lines)

    usage = (
        agent2llm_tokens / watermark.send_limit * 100
        if watermark.send_limit > 0 else 0
    )
    lines.extend([
        f"  Model maximum: {watermark.model_max_context:,}",
        f"  Completion reserve: {watermark.max_tokens:,}",
        f"  Input send limit: {watermark.send_limit:,}",
        f"  Agent2LLM usage: {usage:.1f}%",
        f"  Watermark: {watermark.level}",
    ])
    return "\n".join(lines)


INSTRUCTIONS = dict(
    system_prompt=get_system_prompt,
    env_prompt=get_env_prompt,
    tool_prompt=get_tool_prompt,
    tools=get_tools,
    tools_observation=get_tools_observation,
    set_llm=set_llm,
    models=select_model,
    llm=get_llm,
    messages=get_messages,
    tokens=get_tokens,
)
