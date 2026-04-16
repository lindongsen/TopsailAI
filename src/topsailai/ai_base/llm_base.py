'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import os
import time
import httpx
import httpcore
import openai
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_error,
)
from topsailai.utils import (
    env_tool,
    thread_tool,
)

from .constants import (
    ROLE_ASSISTANT,
)
from .llm_control.exception import (
    JsonError,
    ModelServiceError,
)
from .llm_control.message import (
    get_response_message,
    format_response,
)
from .llm_control.base_class import (
    LLMModelBase,
)

class LLMModel(LLMModelBase):
    """ openai methods """

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
        logger.info("getting llm model [%s] [%s]: ...", self.model_name, api_key[:5] if api_key else None)
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
        return get_response_message(response)

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

        full_content = self.fix_response_content(rsp_obj=response, rsp_content=full_content)
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
            timeout=(5, 300),
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

                result = format_response(rsp_content, rsp_obj, messages=messages)

                if not result:
                    raise TypeError("null of response content: [%s]" % rsp_content)

                if for_response:
                    return (rsp_obj, result)

                return result
            except KeyboardInterrupt:
                # The LLM service has been stuck for a long time, we can proactively retry
                yn = input(">>> LLM Retry [yes/no] ")
                if yn.strip().lower() == "yes":
                    continue
                raise KeyboardInterrupt()
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
                        raise e

                continue
            except (
                    httpx.ReadError,
                    httpcore.ReadError,
                    httpx.RemoteProtocolError,
                ) as e:
                # This problem often occurs with streaming response
                print_error(f"!!! [{i}] ReadError, {e}")
                continue

            except ModelServiceError as e:
                e_str = str(e).lower()
                for key in [
                    "token exceed",
                ]:
                    if key in e_str:
                        raise e

                sec = 30
                # set seconds to sleep
                for key in [
                    "bad_request",
                    "bad request",
                ]:
                    if key in e_str:
                        sec = 1

                print_error(f"!!! [{i}] ModelServiceError, {e}")
                print_error(f"blocking chat {sec}s ...")
                time.sleep(sec)
                continue

            # internal error or bug
            except (
                KeyError,
                Exception,
            ) as e:
                if thread_tool.is_main_thread():
                    print_error(f"Some errors have occurred: [{e}]")
                    logger.exception("some errors have occurred: %s", e)
                    yn = input(">>> LLM Retry [yes/no] ")
                    if yn.strip().lower() == "yes":
                        continue
                raise e

        raise Exception("chat to LLM is failed")
