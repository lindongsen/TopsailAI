'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import os
import sys
import copy
import random
import simplejson

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    format_tool,
)
from topsailai.utils.print_tool import (
    print_debug,
    print_error,
)
from topsailai.context.token import TokenStat

from .message import (
    format_messages,
)

class ContentSender(object):
    """
    Abstract base class for content sending mechanisms.

    This class defines the interface for sending content to various endpoints.
    Subclasses must implement the send method.
    """
    def send(self, content):
        """
        Send content to the configured endpoint.

        Args:
            content (str): The content to send

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError

class ContentStdout(ContentSender):
    """
    Content sender implementation that writes content to standard output.

    This is useful for debugging and command-line applications.
    """
    def send(self, content):
        """
        Write content to standard output.

        Args:
            content (str): The content to write to stdout
        """
        sys.stdout.write(content)


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
    items = env_tool.EnvReaderInstance.get_list_str("TOPSAILAI_MODEL_SETTINGS", separator=';') or \
        env_tool.EnvReaderInstance.get_list_str("MODEL_SETTINGS", separator=';')
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
        ):
        """
        Initialize the LLM model with configuration parameters.

        Args:
            max_tokens (int, optional): Maximum tokens per response. Defaults to 8000.
            temperature (float, optional): Sampling temperature (0.0 to 1.0). Defaults to 0.3.
            top_p (float, optional): Nucleus sampling parameter. Defaults to 0.97.
            frequency_penalty (float, optional): Frequency penalty. Defaults to 0.0.
            model_name (str, optional): Model name. Defaults to environment variable or DeepSeek-V3.1-Terminus.
        """
        self.max_tokens = int(os.getenv("MAX_TOKENS", max_tokens))
        self.temperature = float(os.getenv("TEMPERATURE", temperature))
        self.top_p = float(os.getenv("TOP_P", top_p))
        self.frequency_penalty = float(os.getenv("FREQUENCY_PENALTY", frequency_penalty))

        self.model_name = model_name or self.get_model_name()
        self.model_config = {"api_key": "", "api_base": ""} # in using
        self.model = self.get_llm_model() # in using

        # multiple models, list_dict, _model=self.get_llm_model(model_config)
        self.models = [] # supported
        self.get_llm_models()

        logger.info(f"model={self.model_name}, max_tokens={self.max_tokens}")

        self.tokenStat = TokenStat(id(self))

        self.content_senders = [] # instances of base class ContentSender

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

    def __del__(self):
        """
        Cleanup method called when the object is destroyed.

        Stops the token statistics tracking thread.
        """
        self.tokenStat.flag_running = False

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

    def build_parameters_for_chat(self, messages, stream=False, tools=None, tool_choice="auto"):
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
        messages = format_messages(messages, key_name="step_name", value_name="raw_text")
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

        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice

        return params

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

        return

    def format_null_response_content(self, rsp_obj, rsp_content:str) -> str:
        if rsp_content:
            return rsp_content

        ccm = self.get_response_message(rsp_obj)
        if ccm.tool_calls:
            print_error("LLM makes a mistake, fix it: missing action")
            return format_tool.TOPSAILAI_STEP_ACTION
        return rsp_content


    def fix_response_content(self, rsp_obj, rsp_content:str) -> str:
        """ return new response content """
        if not rsp_content:
            rsp_content = self.format_null_response_content(rsp_obj, rsp_content)

        return rsp_content
