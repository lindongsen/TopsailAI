"""Provider-neutral LLM configuration helpers.

This module owns stateless helpers that read and merge LLM configuration from
the environment: model-settings parsing, JSON-object environment parsing, and
the global / model-specific ``extra_body`` configuration. It is intentionally
provider-neutral: it does not import OpenAI, HTTPX, or HTTPCore.
``LLMModelBase.build_parameters_for_chat`` remains responsible for assembling
the chat-request parameters and applying these helpers.
"""

import copy
import simplejson

from topsailai.logger import logger
from topsailai.utils import format_tool
from topsailai.utils.env_tool import EnvReaderInstance


def parse_model_settings():
    """Parse model settings from the MODEL_SETTINGS environment variable.

    The variable should contain settings in the format: key1=value1,key2=value2;key3=value3,key4=value4

    Items are separated by ';', and within each item, key-value pairs are separated by ','.

    Each key-value pair is separated by '='.

    Returns a list of dictionaries, where each dictionary represents one item.

    Example:

        MODEL_SETTINGS="k1_a=v1_a,k2_a=v2_a;k1_b=v1_b,k2_b=v2_b"

        Returns: [{"k1_a": "v1_a", "k2_a": "v2_a"}, {"k1_b": "v1_b", "k2_b": "v2_b"}]

    """
    items = EnvReaderInstance.get_list_str("TOPSAILAI_MODEL_SETTINGS", separator=';') or \
        EnvReaderInstance.get_list_str("MODEL_SETTINGS", separator=';')
    result = []
    if not items:
        return result
    for item in items:
        d = format_tool.parse_str_to_dict(item, item_separator=',', kv_separator='=', kv_strip=True)
        if d:
            result.append(d)
    return result


def merge_dicts(base, override):
    """Recursively merge dictionaries, giving override values precedence."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def get_json_object_from_env(key):
    """Parse an optional JSON object from an environment variable."""
    raw = EnvReaderInstance.get(key, default="")
    if not raw or not raw.strip():
        return {}
    try:
        parsed = simplejson.loads(raw.strip())
    except Exception:
        logger.warning("invalid JSON in %s: %s", key, raw)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must be a JSON object", key)
        return {}
    return parsed


def get_configured_extra_body():
    """Parse provider-specific fields from TOPSAILAI_LLM_EXTRA_BODY."""
    return get_json_object_from_env("TOPSAILAI_LLM_EXTRA_BODY")


def get_configured_model_extra_body(model_name):
    """Return provider-specific fields configured for an exact model name."""
    configured_map = get_json_object_from_env(
        "TOPSAILAI_LLM_EXTRA_BODY_MAP"
    )
    model_extra_body = configured_map.get(model_name)
    if model_extra_body is None:
        return {}
    if not isinstance(model_extra_body, dict):
        logger.warning(
            "TOPSAILAI_LLM_EXTRA_BODY_MAP value for model %s must be a JSON object",
            model_name,
        )
        return {}
    return model_extra_body


def get_first_byte_timeout_config(env_reader=None):
    """Read first-byte timeout configuration from environment variables.

    Args:
        env_reader: Optional reader exposing ``get`` and ``check_bool``.
            Defaults to ``EnvReaderInstance``.

    Returns:
        tuple: (first_byte_timeout, raise_on_timeout)
            first_byte_timeout (float): threshold in seconds; ``<= 0`` disables.
            raise_on_timeout (bool): whether the caller should raise on timeout.
    """
    if env_reader is None:
        env_reader = EnvReaderInstance
    first_byte_timeout = env_reader.get(
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT",
        default=180,
        formatter=float,
    )
    if first_byte_timeout is None:
        first_byte_timeout = 180

    raise_on_first_byte_timeout = env_reader.check_bool(
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE",
        default=False,
    )
    return first_byte_timeout, raise_on_first_byte_timeout
