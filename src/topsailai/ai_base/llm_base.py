import os
import sys
import copy
import time
import random
import simplejson
import openai
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_error,
    print_debug,
)
from topsailai.utils.json_tool import to_json_str
from topsailai.utils import (
    env_tool,
    format_tool,
)
from topsailai.context.token import TokenStat

from .constants import (
    ROLE_ASSISTANT,
)


class JsonError(Exception):
    """ invalid json string """
    pass


def _to_list(obj):
    """
    Convert an object to a list if it is not already a list.

    Args:
        obj: The object to convert. Can be any type.

    Returns:
        list or None: Returns the object as a list if it's a list-like type,
        returns None if obj is None, otherwise returns a single-item list containing obj.

    Examples:
        >>> _to_list([1, 2, 3])
        [1, 2, 3]
        >>> _to_list("hello")
        ["hello"]
        >>> _to_list(None)
        None
        >>> _to_list((1, 2, 3))
        [1, 2, 3]
    """
    if isinstance(obj, list):
        return obj
    if obj is None:
        return None
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return [obj]

def _format_messages(messages, key_name, value_name):
    """
    Format messages to a specific format for the assistant.

    This function processes messages to apply TopsailAI-specific formatting
    when the first message contains the TopsailAI format prefix.

    Args:
        messages (list): List of message dictionaries with 'content' keys
        key_name (str): The key name to use for formatting
        value_name (str): The value name to use for formatting

    Returns:
        list: The formatted messages list

    Note:
        Only processes messages starting from index 2 (skipping system and user messages)
        that contain JSON-like content (starting with '[' or '{')
    """
    func_format = None  # func(content, key_name, value_name)

    if format_tool.TOPSAILAI_FORMAT_PREFIX in messages[0]["content"]:
        func_format = format_tool.to_topsailai_format

    if func_format is None:
        return messages

    for msg in messages[2:]:
        if msg["content"][0] in ["[", "{"]:
            new_content = func_format(
                msg["content"],
                key_name=key_name,
                value_name=value_name,
            )
            if new_content:
                msg["content"] = new_content.strip()

    #logger.info(simplejson.dumps(messages, indent=2, default=str))

    return messages

def _format_response(response):
    """
    Format response to a standardized list format for internal use.

    This function handles various response formats and converts them to a
    consistent list-of-dictionaries format. It supports:
    - Already formatted lists/dictionaries
    - JSON strings
    - TopsailAI format strings

    Args:
        response: The response to format. Can be list, dict, or string.

    Returns:
        list: A list of dictionaries in standardized format

    Raises:
        JsonError: If the response cannot be parsed after multiple attempts

    Note:
        Attempts parsing up to 3 times, handling TopsailAI format first,
        then falling back to standard JSON parsing.
    """
    if isinstance(response, (list, dict)):
        return _to_list(response)

    if isinstance(response, str):
        response = response.strip()
        if not response:
            raise JsonError("null of response")

    for count in range(3):
        try:
            if response.startswith(format_tool.TOPSAILAI_FORMAT_PREFIX) or \
                f"\n{format_tool.TOPSAILAI_FORMAT_PREFIX}" in response:
                    if count:
                        # no need retry
                        break
                    return format_tool.format_dict_to_list(
                        format_tool.parse_topsailai_format(response),
                        key_name="step_name",
                        value_name="raw_text",
                    )

            response = to_json_str(response)
            return _to_list(simplejson.loads(response))
        except Exception as e:
            print_error(f"parsing response: {e}\n>>>\n{response}\n<<<\nretrying times: {count}")

    raise JsonError("invalid json string")


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
    settings_str = os.getenv("MODEL_SETTINGS")
    if not settings_str:
        return []
    items = settings_str.split(';')
    result = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        kv_pairs = item.split(',')
        d = {}
        for kv in kv_pairs:
            kv = kv.strip()
            if '=' in kv:
                k, v = kv.split('=', 1)
                d[k.strip()] = v.strip()
        if d:  # only append if dict is not empty
            result.append(d)
    return result


class LLMModel(object):
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

        logger.info(f"model={self.model_name}, max_tokens={max_tokens}")

        self.tokenStat = TokenStat(id(self))

        self.content_senders = [] # instances of base class ContentSender

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
        _format_messages(messages, key_name="step_name", value_name="raw_text")
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


    #################################################################
    # openai methods
    #################################################################

    def get_model_name(self, default="DeepSeek-V3.1-Terminus"):
        return os.getenv("OPENAI_MODEL", default)

    def get_llm_model(self, api_key=None, api_base=None):
        """
        Create an OpenAI-compatible chat model object.

        Args:
            api_key (str, optional): API key for authentication. Defaults to environment variable.
            api_base (str, optional): Base URL for API endpoint. Defaults to environment variable.

        Returns:
            object: OpenAI chat completions object
        """
        logger.info("getting llm model ...")
        return openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
            base_url=api_base or os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        ).chat.completions

    def get_response_message(self, response) -> ChatCompletionMessage:
        """
        Extract the message from the API response.

        Args:
            response: The API response object

        Returns:
            ChatCompletionMessage: The assistant's message from the response

        Example:
            ChatCompletionMessage(
                content='',
                refusal=None,
                role='assistant',
                annotations=None,
                audio=None,
                function_call=None,
                tool_calls=None),
                refs=None,
                service_tier=None
            )
        """
        if isinstance(response, ChatCompletionMessage):
            return response
        return response.choices[0].message

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

    def call_llm_model(self, messages, tools=None, tool_choice="auto"):
        """
        Call the LLM model with the provided messages and tools.

        Args:
            messages (list): List of message dictionaries
            tools (list, optional): List of available tools. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".

        Returns:
            tuple: (response object, content string)

        Raises:
            TypeError: If no response or empty response is received
        """
        self.tokenStat.add_msgs(messages)

        response = self.chat_model.create(
            **self.build_parameters_for_chat(
                messages,
                tools=tools, tool_choice=tool_choice,
            )
        )

        self.tokenStat.output_token_stat()

        full_content = response.choices[0].message.content

        self.fix_response_content(rsp_obj=response, rsp_content=full_content)
        self.check_response_content(rsp_obj=response, rsp_content=full_content)

        self.send_content(full_content)

        return (response, full_content)

    def call_llm_model_by_stream(self, messages, tools=None, tool_choice="auto"):
        """
        Call the LLM model with streaming response.

        Args:
            messages (list): List of message dictionaries
            tools (list, optional): List of available tools. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".

        Returns:
            tuple: (response object, concatenated content string)
        """
        self.tokenStat.add_msgs(messages)

        response = self.chat_model.create(
            **self.build_parameters_for_chat(
                messages, stream=True,
                tools=tools, tool_choice=tool_choice,
            )
        )

        full_content = ""
        full_tool_calls_dict = {}
        for chunk in response:
            delta_obj = chunk.choices[0].delta

            # content
            delta_content = delta_obj.content
            if delta_content:
                full_content += delta_content
                self.send_content(delta_content)

            # tool_calls
            for tool_call in delta_obj.tool_calls or []:
                # place object
                _index = tool_call.index
                if _index not in full_tool_calls_dict:
                    full_tool_calls_dict[_index] = {
                        "id": "",
                        "function": {
                            "name": "",
                            "arguments": "",
                        },
                    }
                curr_tool_call = full_tool_calls_dict[_index]

                # pass value
                if tool_call.id:
                    curr_tool_call["id"] = tool_call.id
                if tool_call.function:
                    if "function" not in curr_tool_call:
                        curr_tool_call["function"] = {
                            "name": "",
                            "arguments": "",
                        }
                    if tool_call.function.name:
                        curr_tool_call["function"]["name"] = tool_call.function.name
                    if tool_call.function.arguments:
                        curr_tool_call["function"]["arguments"] += tool_call.function.arguments
        # enf for chunk

        # generate tool_calls
        full_tool_calls_list = []
        if full_tool_calls_dict:
            for _index in sorted(full_tool_calls_dict.keys()):
                tool_call = full_tool_calls_dict[_index]
                tool_call["type"] = "function"
                full_tool_calls_list.append(
                    ChatCompletionMessageToolCall(**tool_call)
                )

        if env_tool.is_debug_mode():
            print()

        self.tokenStat.output_token_stat()

        full_content = full_content.strip()

        # ChatCompletionMessage
        response_ccm = ChatCompletionMessage(
            role=ROLE_ASSISTANT,
            content=full_content,
            tool_calls=full_tool_calls_list,
        )

        full_content = self.fix_response_content(rsp_obj=response_ccm, rsp_content=full_content)
        self.check_response_content(rsp_obj=response_ccm, rsp_content=full_content)

        return (response_ccm, full_content)

    def chat(
            self, messages,
            for_raw=False,
            for_stream=False,
            for_response=False,
            tools=None,
            tool_choice="auto",
        ):
        """
        Main chat method with comprehensive error handling and retry logic.

        Args:
            messages (list): List of message dictionaries
            for_raw (bool, optional): Return raw response content. Defaults to False.
            for_stream (bool, optional): Use streaming mode. Defaults to False.
            for_response (bool, optional): Return response object along with content. Defaults to False.
            tools (list, optional): List of available tools. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".

        Returns:
            Various formats based on parameters:
            - for_raw=True: Raw content string
            - for_response=True: Tuple (response object, formatted content list)
            - Default: Formatted content list

        Raises:
            Exception: If chat fails after maximum retry attempts

        Note:
            Implements exponential backoff and specific error handling for
            various OpenAI API errors including rate limiting, timeouts, etc.
        """
        retry_times = 10
        err_count_map = {}

        rsp_content = None
        rsp_obj = None

        for i in range(100):
            if i > retry_times:
                break

            if i > 0:
                sec = (i%retry_times)*5
                if sec <= 0:
                    sec = 3
                if sec > 120:
                    sec = 120
                print_error(f"[{i}] blocking chat {sec}s ...")
                time.sleep(sec)

            try:
                if for_stream:
                    rsp_obj, rsp_content = self.call_llm_model_by_stream(
                        messages,
                        tools=tools, tool_choice=tool_choice,
                    )
                else:
                    rsp_obj, rsp_content = self.call_llm_model(
                        messages,
                        tools=tools, tool_choice=tool_choice,
                    )

                if for_raw:
                    return rsp_content

                result = _format_response(rsp_content)

                if for_response:
                    return (rsp_obj, result)

                return result
            except JsonError as e:
                print_error(f"!!! [{i}] JsonError, {e}")
                continue
            except openai.RateLimitError as e:
                print_error(f"!!! [{i}] RateLimitError, {self.model_config["api_key"][:7]}, {e}")
                if i > 7:
                    retry_times += 1
                continue
            except TypeError as e:
                print_error(f"!!! [{i}] TypeError, {e}")
                continue
            except openai.InternalServerError as e:
                print_error(f"!!! [{i}] InternalServerError, {e}")
                if i > 7:
                    retry_times += 1

                if 'InternalServerError' not in err_count_map:
                    err_count_map["InternalServerError"] = 0
                err_count_map["InternalServerError"] += 1

                if err_count_map["InternalServerError"] > 5:
                    self.rebuild_llm_models()

                continue
            except openai.APIConnectionError as e:
                print_error(f"!!! [{i}] APIConnectionError, {e}")
                if i > 7:
                    retry_times += 1
                continue
            except openai.APITimeoutError as e:
                print_error(f"!!! [{i}] APITimeoutError, {e}")
                if i > 7:
                    retry_times += 1
                continue
            except openai.PermissionDeniedError as e:
                print_error(f"!!! [{i}] PermissionDeniedError, {e}")
                continue
            except openai.BadRequestError as e:
                # I don't know why some large model services return this issue, but retrying usually resolves it.
                print_error(f"!!! [{i}] BadRequestError, {e}")

                # case: Requested token count exceeds the model's maximum context length
                e_str = str(e).lower()
                for key in [
                    "exceed",
                    "maximum context",
                ]:
                    if key in e_str:
                        break

                continue

        raise Exception("chat to LLM is failed")
