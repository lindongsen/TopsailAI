'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import os
import time
import threading
import httpx
import httpcore
import openai
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.completion_usage import CompletionUsage, PromptTokensDetails

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_error,
    print_warning,
)
from topsailai.utils import (
    env_tool,
    thread_tool,
    qos_tool,
    input_tool,
)
from topsailai.utils.input_tool import input_yes_or_no
from topsailai.utils.state_visualizer import (
    StateVisualizer,
    VisualizationState,
)
from topsailai.utils.thread_local_tool import (
    get_agent_runtime_input,
)

from .constants import (
    ROLE_ASSISTANT,
    LLM_KEYWORD_SERVICE,
    DEFAULT_LLM_SLOW_CHAT_THRESHOLD,
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

# Module-level singleton visualizer used by all LLMModel instances.
_state_visualizer = StateVisualizer()
_state_visualizer.start()


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

    def get_response_usage(self, response) -> CompletionUsage:
        try:
            return response.usage
        except Exception:
            pass
        return None
    def _get_first_byte_timeout_config(self):
        """Read first-byte timeout configuration from environment variables.

        Returns:
            tuple: (first_byte_timeout, raise_on_timeout)
                first_byte_timeout (float): threshold in seconds; ``<= 0`` disables.
                raise_on_timeout (bool): whether to raise ``openai.APITimeoutError``.
        """
        first_byte_timeout = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT",
            default=180,
            formatter=float,
        )
        if first_byte_timeout is None:
            first_byte_timeout = 180

        raise_on_first_byte_timeout = env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE",
            default=False,
        )
        return first_byte_timeout, raise_on_first_byte_timeout

    def _make_first_byte_timeout_error(self, first_byte_timeout):
        """Construct an ``openai.APITimeoutError`` for first-byte timeout.

        The OpenAI exception constructor only accepts a ``request`` argument,
        so the message is attached after construction in a defensive way.
        """
        message = f"First byte timeout after {first_byte_timeout}s"
        exc = openai.APITimeoutError(request=None)
        if hasattr(exc, "message"):
            exc.message = message
        if hasattr(exc, "args"):
            exc.args = (message,)
        return exc

    def _log_first_byte_timeout(self, elapsed, first_byte_timeout):
        """Log a first-byte timeout warning using project conventions."""
        print_warning(
            f"{LLM_KEYWORD_SERVICE}: first byte timeout threshold reached/exceeded: "
            f"elapsed {elapsed:.1f}s >= threshold {first_byte_timeout}s"
        )

    def _create_with_first_byte_timeout(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        stream=False,
        first_byte_timeout=180,
        raise_on_timeout=False,
    ):
        """Call ``chat_model.create()`` with an optional first-byte timeout.

        For non-streaming requests the timeout covers the blocking period before
        the response object is returned. For streaming requests it covers the
        blocking period before the ``Stream`` object is returned; the caller
        should still wrap the returned iterator with
        ``iter_stream_with_first_byte_timeout`` to enforce a timeout on the
        first chunk.

        Args:
            messages (list): List of message dictionaries.
            tools (list, optional): List of available tools. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".
            stream (bool, optional): Whether to request a streaming response.
            first_byte_timeout (float): Threshold in seconds. ``<= 0`` disables.
            raise_on_timeout (bool): If True, raise ``openai.APITimeoutError``
                when the first byte exceeds the threshold.

        Returns:
            For ``stream=False``: the response object.
            For ``stream=True``: tuple ``(response, create_timed_out)`` where
            ``create_timed_out`` indicates that the create() blocking period
            already exceeded the threshold.
        """
        params = self.build_parameters_for_chat(
            messages, stream=stream, tools=tools, tool_choice=tool_choice
        )

        if first_byte_timeout is None or first_byte_timeout <= 0:
            response = self.chat_model.create(timeout=(5, 300), **params)
            if stream:
                return response, False
            return response

        result = [None]
        first_exc = [None]
        got_result = threading.Event()

        def _create():
            try:
                result[0] = self.chat_model.create(timeout=(5, 300), **params)
            except Exception as e:
                first_exc[0] = e
            finally:
                got_result.set()

        start_time = time.monotonic()
        create_thread = threading.Thread(target=_create, daemon=True)
        create_thread.start()

        timed_out = not got_result.wait(timeout=first_byte_timeout)
        elapsed = time.monotonic() - start_time

        if timed_out:
            self._log_first_byte_timeout(elapsed, first_byte_timeout)
            if raise_on_timeout:
                raise self._make_first_byte_timeout_error(first_byte_timeout)
            # Timeout without raise: wait for the actual result so the caller
            # still receives a valid response. The timeout acts as a monitoring
            # signal rather than a hard deadline in this mode.
            got_result.wait()
            if first_exc[0] is not None:
                raise first_exc[0]
            if stream:
                return result[0], True
            return result[0]

        if first_exc[0] is not None:
            raise first_exc[0]

        if stream:
            return result[0], False
        return result[0]


    @_state_visualizer.visualize_state(VisualizationState.THINKING)
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
            openai.APITimeoutError: If TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE is
                enabled and the first byte exceeds the configured threshold.
        """
        self.tokenStat.add_msgs(messages)

        first_byte_timeout, raise_on_first_byte_timeout = self._get_first_byte_timeout_config()

        response = self._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_first_byte_timeout,
        )
        self.tokenStat.output_token_stat(self.get_response_usage(response))

        full_content = response.choices[0].message.content

        full_content = self.fix_response_content(rsp_obj=response, rsp_content=full_content)
        self.check_response_content(rsp_obj=response, rsp_content=full_content)

        self.send_content(full_content)

        return (response, full_content)

    def iter_stream_with_first_byte_timeout(
        self,
        stream,
        first_byte_timeout=180,
        raise_on_timeout=False,
        create_timed_out=False,
    ):
        """Wrap a stream iterator to enforce a first-byte timeout.

        The timeout is applied only to the first chunk. Subsequent chunks are
        yielded without additional timeout logic. When the timeout is disabled
        (``first_byte_timeout <= 0``), the stream is passed through unchanged.

        Args:
            stream: The stream iterator to wrap.
            first_byte_timeout (float): Threshold in seconds for the first chunk.
                Values of ``0`` or less disable the timeout.
            raise_on_timeout (bool): If True, raise openai.APITimeoutError when
                the first chunk exceeds the threshold so the caller can retry.
            create_timed_out (bool): If True, the blocking period before the
                stream was returned already exceeded the threshold and was
                logged. This avoids double-warning for the same slow event.

        Yields:
            Chunks from the wrapped stream.

        Raises:
            openai.APITimeoutError: If raise_on_timeout is True and the first
                chunk takes longer than first_byte_timeout seconds.
        """
        if first_byte_timeout is None or first_byte_timeout <= 0:
            yield from stream
            return

        first_chunk = [None]
        first_exc = [None]
        got_result = threading.Event()

        def _fetch_first():
            try:
                first_chunk[0] = next(stream)
            except StopIteration:
                pass
            except Exception as e:
                first_exc[0] = e
            finally:
                got_result.set()

        start_time = time.monotonic()
        fetch_thread = threading.Thread(target=_fetch_first, daemon=True)
        fetch_thread.start()

        timed_out = not got_result.wait(timeout=first_byte_timeout)
        elapsed = time.monotonic() - start_time

        if timed_out:
            if hasattr(stream, "close"):
                try:
                    stream.close()
                except Exception:
                    pass
            if not create_timed_out:
                self._log_first_byte_timeout(elapsed, first_byte_timeout)
            if raise_on_timeout:
                raise self._make_first_byte_timeout_error(first_byte_timeout)
            # Timeout without raise: stop iteration so the caller does not
            # block indefinitely waiting for a response that already missed
            # its deadline.
            return

        if first_exc[0] is not None:
            raise first_exc[0]

        if first_chunk[0] is None:
            # Empty stream or StopIteration before any chunk.
            return

        if elapsed > first_byte_timeout and not create_timed_out:
            self._log_first_byte_timeout(elapsed, first_byte_timeout)

        yield first_chunk[0]
        for chunk in stream:
            yield chunk
    @_state_visualizer.visualize_state(VisualizationState.THINKING)
    def call_llm_model_by_stream(self, messages, tools=None, tool_choice="auto"):
        """
        Call the LLM model with streaming response.

        Args:
            messages (list): List of message dictionaries
            tools (list, optional): List of available tools. Defaults to None.
            tool_choice (str, optional): Tool choice strategy. Defaults to "auto".

        Returns:
            tuple: (response object, concatenated content string)

        Raises:
            openai.APITimeoutError: If TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE is
                enabled and the first byte exceeds the configured threshold.
        """
        self.tokenStat.add_msgs(messages)

        first_byte_timeout, raise_on_first_byte_timeout = self._get_first_byte_timeout_config()

        # Capture the stream start time before creating the request so that
        # first-byte latency includes request creation + streaming startup.
        stream_start_time = time.monotonic()

        response, create_timed_out = self._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_first_byte_timeout,
        )

        full_content = ""
        full_tool_calls_dict = {}

        usage = CompletionUsage(
            completion_tokens=0, prompt_tokens=0, total_tokens=0,
            prompt_tokens_details=PromptTokensDetails(audio_tokens=0, cached_tokens=0),
        )

        first_byte_ms = None

        for chunk in self.iter_stream_with_first_byte_timeout(
            response,
            first_byte_timeout,
            raise_on_timeout=raise_on_first_byte_timeout,
            create_timed_out=create_timed_out,
        ):
            delta_obj = None
            if len(chunk.choices):
                delta_obj = chunk.choices[0].delta
            try:
                delta_usage = self.get_response_usage(chunk)
                if delta_usage:
                    usage.prompt_tokens_details.cached_tokens += delta_usage.prompt_tokens_details.cached_tokens
            except Exception:
                pass
            if delta_obj is None:
                continue

            # Record first-byte timing on the first chunk that carries content
            # or tool-call data. This measures the time from stream start to the
            # first useful response byte.
            if first_byte_ms is None:
                first_byte_ms = (time.monotonic() - stream_start_time) * 1000

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

        # Record first-byte timing for stream responses.
        if first_byte_ms is not None:
            self.tokenStat.add_first_byte(first_byte_ms)

        # Notify all content senders that the stream has finished so they can
        # emit a final newline or release any in-progress rendering state.
        for sender in self.content_senders:
            if hasattr(sender, "finish"):
                sender.finish()

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

        self.tokenStat.output_token_stat(usage)

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
                with qos_tool.log_if_slow(
                        env_tool.EnvReaderInstance.get(
                            "TOPSAILAI_LLM_SLOW_CHAT_THRESHOLD",
                            default=DEFAULT_LLM_SLOW_CHAT_THRESHOLD,
                            formatter=int,
                        ) or DEFAULT_LLM_SLOW_CHAT_THRESHOLD,
                        f"{LLM_KEYWORD_SERVICE}: slow chat",
                    ) as _info:
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

                    # set qos info
                    _info["current_tokens"] = self.tokenStat.current_tokens
                    _info["cached_tokens"] = self.tokenStat.current_cached_tokens

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
                input_func = get_agent_runtime_input()
                if input_func is None:
                    input_func = input
                if input_yes_or_no(">>> LLM Retry [yes/no] ", input_func):
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
                    httpx.ReadTimeout,
                    httpcore.ReadTimeout,
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

                print_error(f"!!! [{i}] {LLM_KEYWORD_SERVICE}: {e}")
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
                    input_func = get_agent_runtime_input()
                    if input_func is None:
                        input_func = input
                    if input_yes_or_no(">>> LLM Retry [yes/no] ", input_func):
                        continue
                raise e

        raise Exception("chat to LLM is failed")
