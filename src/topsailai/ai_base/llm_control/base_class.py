'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import os
import copy
import random
import simplejson

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    format_tool,
    message_tool,
    text_tool,
)
from topsailai.utils.env_tool import EnvReaderInstance  # For test compatibility
from topsailai.utils.print_tool import (
    print_debug,
    print_error,
    print_critical,
)
from topsailai.ai_base.constants import (
    LLM_KEYWORD_MISTAKE,
)
from topsailai.context.llm_request_stat import LLMRequestStat
from topsailai.context.llm_state_visualizer import LLMStateVisualizer
from topsailai.context.token import (
    TokenStat,
    count_tokens,
)

from .message import (
    format_messages,
)
from .exception import (
    ModelServiceError,
    LLMServiceSpecialResponseError,
)
from .content_endpoint import (
    ContentSender,
    ContentStdout,
)


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

class LLMModelBase(object):
    """
    Main LLM model class for handling interactions with language models.

    This class provides a unified interface for communicating with various
    LLM providers through the OpenAI-compatible API. It supports multiple
    models, token tracking, content sending, and error handling.

    Attributes:
        max_tokens (int): Maximum tokens to generate
        temperature (float): Sampling temperature
        top_p (float): Nucleus sampling parameter
        frequency_penalty (float): Frequency penalty for repetition control
        model_name (str): Name of the model to use
        model_config (dict): Current model configuration
        model: Current model object for API calls
        models (list): List of available model configurations
        tokenStat (TokenStat): Token statistics tracker
        content_senders (list): List of content sender instances
    """
    def __init__(
            self,
            max_tokens=8000,
            temperature=0.3,
            top_p=0.97,
            frequency_penalty=0.0,
            model_name=None,
            llm_request_stat=None,
            state_visualizer=None,
        ):
        """
        Initialize the LLM model with configuration parameters.

        Args:
            max_tokens (int, optional): Maximum tokens per response. Defaults to 8000.
            temperature (float, optional): Sampling temperature (0.0 to 1.0). Defaults to 0.3.
            top_p (float, optional): Nucleus sampling parameter. Defaults to 0.97.
            frequency_penalty (float, optional): Frequency penalty. Defaults to 0.0.
            model_name (str, optional): Model name. Defaults to environment variable or DeepSeek-V3.1-Terminus.
            llm_request_stat (LLMRequestStat, optional): Context-local request tracker.
            state_visualizer (LLMStateVisualizer, optional): Context-local state visualizer.
        """
        self.max_tokens = EnvReaderInstance.get_with_fallback(
            "TOPSAILAI_MAX_COMPLETION_TOKENS", "MAX_TOKENS",
            default=max_tokens, formatter=int,
        )
        self.temperature = EnvReaderInstance.get_with_fallback(
            "TOPSAILAI_TEMPERATURE", "TEMPERATURE",
            default=temperature, formatter=float,
        )
        self.top_p = EnvReaderInstance.get_with_fallback(
            "TOPSAILAI_TOP_P", "TOP_P", default=top_p, formatter=float,
        )
        self.frequency_penalty = EnvReaderInstance.get_with_fallback(
            "TOPSAILAI_FREQUENCY_PENALTY", "FREQUENCY_PENALTY",
            default=frequency_penalty, formatter=float,
        )

        self.model_name = model_name or self.get_model_name()
        self.model_config = {"api_key": "", "api_base": ""} # in using
        self.model = self.get_llm_model() # in using

        # multiple models, list_dict, _model=self.get_llm_model(model_config)
        self.models = [] # supported
        self.get_llm_models()

        logger.info(f"model={self.model_name}, max_tokens={self.max_tokens}")

        self.tokenStat = TokenStat(id(self))
        self.llm_request_stat = llm_request_stat or LLMRequestStat()
        self.state_visualizer = state_visualizer or LLMStateVisualizer(
            self.llm_request_stat
        )

        self.content_senders = [] # instances of base class ContentSender

    def _get_llm_request_stat(self):
        """Return this model's request tracker, creating a local legacy fallback."""
        request_stat = getattr(self, "llm_request_stat", None)
        if request_stat is None:
            request_stat = LLMRequestStat()
            self.llm_request_stat = request_stat
        return request_stat

    def _get_state_visualizer(self):
        """Return this model's visualizer, creating a local legacy fallback."""
        visualizer = getattr(self, "state_visualizer", None)
        if visualizer is None:
            visualizer = LLMStateVisualizer(self._get_llm_request_stat())
            self.state_visualizer = visualizer
        return visualizer

    def _record_llm_request_stat(self, record_method_name):
        """Apply one statistics update without producing duplicate output."""
        request_stat = self._get_llm_request_stat()
        getattr(request_stat, record_method_name)()

    def _record_llm_request(self):
        """Record one provider request attempt."""
        self._record_llm_request_stat("record_request")

    def _record_llm_request_success(self):
        """Record one successful provider request."""
        self._record_llm_request_stat("record_request_success")

    def _record_llm_request_failure(self):
        """Record one failed provider request."""
        self._record_llm_request_stat("record_request_failure")

    def _record_llm_response_content_error(self):
        """Record one tool-response content error."""
        self._record_llm_request_stat("record_response_content_error")

    def __str__(self) -> str:
        parts = {
            # basic config
            "model_name": self.model_name,
            "api_base": self.model_config.get("api_base") or os.getenv("OPENAI_API_BASE"),
            "api_key": (self.model_config.get("api_key") or os.getenv("OPENAI_API_KEY") or "")[:7] + "...",
            "models_count": len(self.models),

            # advance config
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
        }
        result = "\n"
        # agent indent is 2, llm indent is 4
        for k, v in parts.items():
            result += f"    {k}={v}\n"
        return result

    #################################################################################
    # NotImplemented
    #################################################################################
    def get_model_name(self, default=""):
        """ return a model name """
        raise NotImplementedError

    def get_llm_model(self, api_key=None, api_base=None):
        """ create a model object """
        raise NotImplementedError

    def get_response_message(self, response):
        """ Extract the message from the API response. """
        raise NotImplementedError

    def chat(self, *args, **kwargs):
        raise NotImplementedError

    #################################################################################
    # base functions
    #################################################################################

    def send_content(self, content):
        """
        Send content through all registered content senders.

        Args:
            content (str): The content to send through all registered senders
        """
        for sender in self.content_senders:
            sender.send(content)
        return

    def close(self) -> None:
        """Stop context-local background workers; repeated calls are safe."""
        visualizer = getattr(self, "state_visualizer", None)
        if visualizer is not None:
            visualizer.stop()
        token_stat = getattr(self, "tokenStat", None)
        if token_stat is not None:
            token_stat.flag_running = False

    def __del__(self):
        """Best-effort cleanup for callers that do not explicitly close the model."""
        self.close()

    @property
    def chat_model(self):
        """
        Get an available model object for chatting.

        If multiple models are configured, randomly selects one from the available pool.

        Returns:
            object: The chat model object for API calls
        """
        if self.models:
            self.model_config = random.choice(self.models)
            self.model = self.model_config["_model"]
        return self.model

    def get_llm_models(self):
        """
        Initialize and add models to self.models from environment settings.

        Parses model settings from environment variables and creates model
        configurations for each available model endpoint.

        Returns:
            list: List of model configuration dictionaries

        Note:
            Each model configuration contains:
            - api_key: API key for authentication
            - api_base: Base URL for the API endpoint
            - _model: The actual chat model object
        """
        model_settings = parse_model_settings()
        if not model_settings:
            return
        for model_config in model_settings:
            _model = self.get_llm_model(
                api_key=model_config["api_key"],
                api_base=model_config.get("api_base"),
            )
            model_config["_model"] = _model
            self.models.append(model_config)
        return self.models

    def rebuild_llm_models(self):
        """
        Rebuild the model configurations.

        Attempts to rebuild the models list first. If no models are found,
        falls back to rebuilding the default model.
        """
        # self.models
        self.models = []
        if self.get_llm_models():
            return

        # self.model
        self.model = self.get_llm_model()
        return

    def build_parameters_for_chat(self, messages, stream=False, tools=None, tool_choice="auto", **options):
        """
        Build parameters for the chat completion API call.

        Args:
            messages (list): List of message dictionaries
            stream (bool, optional): Whether to stream the response. Defaults to False.
            tools (list, optional): List of tools available to the model. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".

        Returns:
            dict: Parameters dictionary for the chat completion API
        """
        messages = copy.deepcopy(messages)
        message_tool.normalize_message_tool_calls(messages, logger=logger)
        messages = format_messages(messages, key_name="step_name", value_name="raw_text")
        message_tool.normalize_message_tool_calls(messages, logger=logger)
        messages = message_tool.drop_orphaned_tool_messages(messages, logger=logger)
        params = dict(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            n=1,
            stop=None,
            stream=stream,
        )

        if stream:
            params.update(
                dict(
                    stream_options={"include_usage": True}
                )
            )

        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice

        # parallel_tool_calls
        if options.get("parallel_tool_calls") is not None:
            params["parallel_tool_calls"] = options["parallel_tool_calls"]
        if "parallel_tool_calls" not in params and not EnvReaderInstance.is_not_config("TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS"):
            params["parallel_tool_calls"] = EnvReaderInstance.check_bool("TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS")

        extra_body = options.get("extra_body")
        if extra_body is not None:
            params["extra_body"] = copy.deepcopy(extra_body)
        configured_extra_body = self._get_configured_extra_body()
        if configured_extra_body:
            params["extra_body"] = self._merge_dicts(
                params.get("extra_body", {}), configured_extra_body
            )
        model_extra_body = self._get_configured_model_extra_body(self.model_name)
        if model_extra_body:
            params["extra_body"] = self._merge_dicts(
                params.get("extra_body", {}), model_extra_body
            )

        return params

    @staticmethod
    def _merge_dicts(base, override):
        """Recursively merge dictionaries, giving override values precedence."""
        merged = copy.deepcopy(base)
        for key, value in override.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = LLMModelBase._merge_dicts(merged[key], value)
                continue
            merged[key] = copy.deepcopy(value)
        return merged

    @staticmethod
    def _get_json_object_from_env(key):
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

    @staticmethod
    def _get_configured_extra_body():
        """Parse provider-specific fields from TOPSAILAI_LLM_EXTRA_BODY."""
        return LLMModelBase._get_json_object_from_env("TOPSAILAI_LLM_EXTRA_BODY")

    @staticmethod
    def _get_configured_model_extra_body(model_name):
        """Return provider-specific fields configured for an exact model name."""
        configured_map = LLMModelBase._get_json_object_from_env(
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

    def debug_response(self, response, content):
        """
        Print debug information about the response if in debug mode.

        Args:
            response: The API response object
            content (str): The response content string
        """
        if not env_tool.is_debug_mode():
            return

        if content is None:
            return
        if response is None:
            return

        content = content.strip()

        def _need_print() -> bool:
            if not content:
                return True
            #if 'tool_call' in content:
            #    return True
            #if '"action"' in content and '"tool_call":' not in content:
            #    return True
            return False

        if _need_print():
            print_debug("[RESPONSE] \n" + simplejson.dumps(response.__dict__, indent=2, ensure_ascii=False, default=str))

        return

    def check_response_content(self, rsp_obj, rsp_content:str):
        """ if error, raise sth. """
        # debug only
        try:
            self.debug_response(rsp_obj, rsp_content)
        except Exception as e:
            print_error(f"[DEBUG] {e}")

        # check content
        if rsp_content is None:
            raise TypeError("no response")

        rsp_content = rsp_content.strip()

        if not rsp_content:
            raise TypeError("null of response")

        # special responses that should trigger a retry
        special_responses = self._get_special_responses_for_retry()
        if special_responses and rsp_content in special_responses:
            raise LLMServiceSpecialResponseError(
                f"LLM returned a special response that requires retry: {rsp_content!r}"
            )

        # exceed max tokens
        txt_content = str(rsp_content)
        max_tokens = self.max_tokens
        current_tokens = count_tokens(txt_content)
        if (current_tokens+max_tokens*0.1) >= max_tokens:
            repetition_result = text_tool.check_repetition(txt_content)
            if repetition_result.get("has_severe_repetition"):
                error_msg = f"{LLM_KEYWORD_MISTAKE}: Severe repetition loop pattern detected!"
                print_critical(f"{error_msg} {repetition_result}")
                if EnvReaderInstance.check_bool(
                    "TOPSAILAI_REFUSE_SEVERE_REPETITION", False
                ):
                    raise ModelServiceError(error_msg, repetition_result)
        return

    def _get_special_responses_for_retry(self):
        """Parse TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY into a list of exact-match strings."""
        raw = EnvReaderInstance.get("TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY", default="[]")
        if not raw or not raw.strip():
            return []
        try:
            parsed = simplejson.loads(raw.strip())
        except Exception:
            logger.warning("invalid JSON in TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY: %s", raw)
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if item is not None]
        return []

    def format_null_response_content(self, rsp_obj, rsp_content:str) -> str:
        if rsp_content:
            return rsp_content

        ccm = self.get_response_message(rsp_obj)
        if ccm.tool_calls:
            # Native tool_call carried on rsp_obj: no mistake log needed.
            return format_tool.TOPSAILAI_STEP_ACTION
        return rsp_content


    def fix_response_content(self, rsp_obj, rsp_content:str) -> str:
        """ return new response content """
        if not rsp_content:
            rsp_content = self.format_null_response_content(rsp_obj, rsp_content)

        return rsp_content
