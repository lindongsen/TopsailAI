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
    Apply a model configuration to the active agent's LLM model.

    Args:
        agent: The current agent instance.
        config (dict): Model configuration containing model_name, api_base, api_key, etc.

    Returns:
        str: Human-readable summary of the applied changes.
    """
    llm_model = agent.llm_model
    old_model_name = llm_model.model_name
    old_api_base = getattr(llm_model.model_config, "api_base", "") or llm_model.model_config.get("api_base", "")
    old_api_key = getattr(llm_model.model_config, "api_key", "") or llm_model.model_config.get("api_key", "")

    new_model_name = config.get("model_name") or config.get("model") or config.get("name") or old_model_name
    new_api_base = config.get("api_base") or config.get("base_url") or old_api_base
    new_api_key = config.get("api_key") or old_api_key

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

    # Apply environment variable values recorded in the model configuration.
    # The 'environment' field is a dict mapping env-var-name -> value.
    environment = config.get("environment")
    if isinstance(environment, dict):
        for env_name, env_value in environment.items():
            os.environ[env_name] = str(env_value)
            print_info(f"Set environment variable: {env_name}={env_value}")

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


INSTRUCTIONS = dict(
    system_prompt=get_system_prompt,
    env_prompt=get_env_prompt,
    tool_prompt=get_tool_prompt,
    tools=get_tools,
    set_llm=set_llm,
    models=select_model,
    llm=get_llm,
    messages=get_messages,
)
