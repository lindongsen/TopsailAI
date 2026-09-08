'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import os
import random
import time

import httpx
import httpcore
import openai

# Fixed prime sleep durations (seconds) used when retrying after
# LLMServiceSpecialResponseError (e.g. "服务器繁忙").
_LLM_SERVICE_SPECIAL_RESPONSE_SLEEP_SECONDS = (
    5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97
)
from openai.types.chat import ChatCompletionMessage
from openai.types.completion_usage import CompletionUsage

from topsailai.logger.log_chat import logger
from topsailai.ai_base.llm_pool import OpenAIClientConfig, acquire, invalidate
from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIResponseAdapter
from topsailai.utils.print_tool import (
    print_error,
    print_info,
    print_warning,
)
from topsailai.utils import (
    env_tool,
    thread_tool,
    qos_tool,
    input_tool,
)
from topsailai.utils.input_tool import input_yes_or_no
from topsailai.context.llm_state_visualizer import visualize_model_state
from topsailai.utils.state_visualizer import VisualizationState
from topsailai.utils.thread_local_tool import (
    get_agent_object,
)

from .constants import (
    ROLE_ASSISTANT,
    LLM_KEYWORD_SERVICE,
    DEFAULT_LLM_SLOW_CHAT_THRESHOLD,
)
from .exception import (
    HardInterruptError,
    LLMBackToChatError,
    LLMRetryExhaustedError,
)
from .llm_control.exception import (
    JsonError,
    ModelServiceError,
    LLMServiceSpecialResponseError,
)
from .llm_control.message import get_response_message, format_response
from .llm_control.configuration import (
    get_first_byte_timeout_config as _get_first_byte_timeout_config,
)
from .llm_control.base_class import (
    LLMModelBase,
)
from .llm_hooks.executor import hook_execute
from .llm_control.model_handles import LLMModelHandleLifecycleMixin
from .llm_control.native_tool_calls import NativeToolCallResponseMixin
from .llm_control.llm_retry import (
    LLMRetryInteractionPolicy,
    read_retry_exhaustion_action as _read_retry_exhaustion_action,
)
from .llm_control.retry_classification import (
    match_non_retryable_bad_request as _match_non_retryable_bad_request,
)

from .llm_control.first_byte_timeout import (
    FirstByteTimeoutMixin,
    iter_with_first_byte_timeout as _iter_with_first_byte_timeout,
)
from .llm_control.request_tracking import (
    _llm_request_started,
    _llm_request_timing_ticket,
    iter_stream_for_request_timing as _iter_stream_for_request_timing,
    log_first_byte_timeout as _log_first_byte_timeout,
    record_llm_request_outcome as _record_llm_request_outcome,
)
from .llm_control.response_events import LLMResponseEventMixin


class LLMModel(
    NativeToolCallResponseMixin,
    LLMResponseEventMixin,
    FirstByteTimeoutMixin,
    LLMModelHandleLifecycleMixin,
    LLMModelBase,
):
    """OpenAI-compatible model with context-local runtime components."""

    def _get_pending_native_tool_call_responses(self):
        """Retain the native pending-response FIFO compatibility seam."""
        return super()._get_pending_native_tool_call_responses()

    def clear_pending_native_tool_call_responses(self):
        """Retain the native pending-response cleanup compatibility seam."""
        return super().clear_pending_native_tool_call_responses()

    def _split_native_tool_call_response(self, rsp_obj, rsp_content):
        """Retain the native tool-call split compatibility seam."""
        return super()._split_native_tool_call_response(rsp_obj, rsp_content)

    def _build_single_native_tool_call_response(self, *, content, tool_call):
        """Build one OpenAI-compatible response for a native tool call."""
        return ChatCompletionMessage(
            role=ROLE_ASSISTANT,
            content=content,
            tool_calls=[tool_call],
        )

    def _on_native_tool_call_responses_cleared(self, pending_count):
        """Log cleanup of pending native tool-call responses."""
        logger.debug(
            "cleared %s pending native tool-call responses",
            pending_count,
        )

    def _on_native_tool_call_response_split(self, total_tool_calls):
        """Report splitting of one native multi-tool-call response."""
        logger.debug(
            "split %s native tool calls into sequential responses",
            total_tool_calls,
        )
        print_info(f"Detected {total_tool_calls} native tool calls")

    def get_model_name(self, default="DeepSeek-V3.1-Terminus"):
        return os.getenv("OPENAI_MODEL", default)

    def _get_llm_model_handles(self):
        """Retain the OpenAI model ownership-record compatibility seam."""
        return super()._get_llm_model_handles()

    def _get_llm_model_handle_registry(self):
        """Retain the OpenAI model handle-registry compatibility seam."""
        return super()._get_llm_model_handle_registry()

    def get_llm_model(self, api_key=None, api_base=None):
        """Return a pooled OpenAI-compatible chat completions resource."""
        effective_api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        effective_api_base = api_base or os.getenv(
            "OPENAI_API_BASE", "https://api.openai.com/v1"
        )
        logger.info("getting llm model [%s]: ...", self.model_name)
        handle = acquire(
            OpenAIClientConfig(
                api_key=effective_api_key,
                base_url=effective_api_base,
                model=self.model_name,
            )
        )
        chat_model = handle.client.chat.completions
        self._register_llm_model_handle(chat_model, handle)
        return chat_model

    def snapshot_llm_model_leases(self):
        """Retain the OpenAI model lease-snapshot compatibility seam."""
        return super().snapshot_llm_model_leases()

    def release_llm_model_leases(self, handles) -> int:
        """Retain the OpenAI model exact-release compatibility seam."""
        return super().release_llm_model_leases(handles)

    def release_llm_model_leases_after(self, snapshot) -> int:
        """Retain the OpenAI model post-snapshot release compatibility seam."""
        return super().release_llm_model_leases_after(snapshot)

    def release_llm_model(self, chat_model) -> bool:
        """Retain the OpenAI model single-release compatibility seam."""
        return super().release_llm_model(chat_model)

    def release_all_llm_models(self) -> int:
        """Retain the OpenAI model release-all compatibility seam."""
        return super().release_all_llm_models()

    def _find_llm_model_handle(self, chat_model):
        """Retain the OpenAI model handle-lookup compatibility seam."""
        return super()._find_llm_model_handle(chat_model)

    def invalidate_llm_model(self, chat_model) -> bool:
        """Retire only the global client generation behind one owned resource."""
        handle = self._find_llm_model_handle(chat_model)
        if handle is None:
            return False
        return invalidate(handle.key)

    def replace_llm_model(self, old_model, api_key=None, api_base=None):
        """Acquire a replacement before releasing the exact old lease."""
        old_handle = self._find_llm_model_handle(old_model)
        new_model = self.get_llm_model(api_key=api_key, api_base=api_base)
        # A cache hit can expose the same chat resource for both generations of
        # ownership. Release the handle captured before acquire, never whichever
        # equal resource was appended most recently.
        if old_handle is not None:
            self.release_llm_model_leases((old_handle,))
        return new_model

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
        """Retain the provider usage compatibility seam."""
        return super().get_response_usage(response)

    def _return_chat_response(
            self,
            rsp_obj,
            rsp_content,
            messages,
            for_raw=False,
            for_response=False,
        ):
        """Retain response compatibility through legacy module adapters."""
        return super()._return_chat_response_with_adapters(
            rsp_obj,
            rsp_content,
            messages,
            for_raw=for_raw,
            for_response=for_response,
            get_agent_object_fn=get_agent_object,
            hook_execute_fn=hook_execute,
            format_response_fn=format_response,
        )

    def _get_first_byte_timeout_config(self):
        """Read first-byte timeout configuration from environment variables.

        Thin wrapper around the provider-neutral helper in ``llm_control``.
        """
        return _get_first_byte_timeout_config(env_tool.EnvReaderInstance)

    def _make_first_byte_timeout_error(self, first_byte_timeout):
        """Construct the provider timeout error through the OpenAI adapter."""
        return OpenAIResponseAdapter.make_first_byte_timeout_error(first_byte_timeout)

    def _log_first_byte_timeout(self, elapsed, first_byte_timeout):
        """Log a first-byte timeout warning using project conventions."""
        return _log_first_byte_timeout(
            elapsed,
            first_byte_timeout,
            warning_func=print_warning,
            service_keyword=LLM_KEYWORD_SERVICE,
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
        """Retain the request-creation first-byte timeout compatibility seam."""
        return super()._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_timeout,
        )

    def _build_first_byte_request_parameters(
        self, messages, *, tools, tool_choice, stream
    ):
        """Build OpenAI-compatible provider request parameters."""
        return self.build_parameters_for_chat(
            messages,
            stream=stream,
            tools=tools,
            tool_choice=tool_choice,
        )

    def _create_first_byte_response(self, params):
        """Create one provider response through the OpenAI adapter."""
        return OpenAIResponseAdapter.create_response(self.chat_model, params)

    def _start_first_byte_request(self):
        """Start request timing for one provider attempt."""
        return self._start_llm_request()

    def _pause_first_byte_request(self, ticket):
        """Pause request timing after provider stream creation."""
        return self._pause_llm_request(ticket)

    def _finish_first_byte_request(self, ticket):
        """Finish request timing after a provider attempt."""
        return self._finish_llm_request(ticket)

    def _publish_first_byte_request_ticket(self, ticket):
        """Publish request timing context in the calling thread."""
        _llm_request_started.set(True)
        _llm_request_timing_ticket.set(ticket)

    def _iter_first_byte_timeout(self, stream, *args, **kwargs):
        """Apply the stream timeout helper through the legacy module seam."""
        return _iter_with_first_byte_timeout(stream, *args, **kwargs)


    def _truncate_event_payload(self, payload, max_bytes):
        """Retain the response-event truncation compatibility seam."""
        return super()._truncate_event_payload(payload, max_bytes)

    def _record_llm_response_event(self, response, is_stream=False, sampled_chunks=None):
        """Retain the response-event configuration and patch compatibility seam."""
        try:
            enabled = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED",
                default=True,
            )
            if not enabled:
                return

            max_payload_bytes = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_LLM_RESPONSE_EVENTS_MAX_PAYLOAD_BYTES",
                default=100000,
                formatter=int,
            )
            if max_payload_bytes is None or max_payload_bytes <= 0:
                max_payload_bytes = 100000

            include_raw = env_tool.EnvReaderInstance.check_bool(
                "TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW",
                default=True,
            )

            from topsailai.events import record_event

            def recorder(payload):
                record_event(
                    "llm.response.raw",
                    payload=payload,
                    source="ai_base.llm_base",
                )

            return super()._record_llm_response_event(
                response,
                is_stream=is_stream,
                sampled_chunks=sampled_chunks,
                enabled=enabled,
                max_payload_bytes=max_payload_bytes,
                include_raw=include_raw,
                recorder=recorder,
            )
        except Exception:
            # Safe hook: never re-raise; never mutate shared state.
            return None

    def _get_llm_response_event_message(self, response):
        """Adapt an OpenAI-compatible response for event serialization."""
        return self.get_response_message(response)

    def _get_llm_response_event_model_name(self):
        """Return the OpenAI-compatible model name for event payloads."""
        return self.model_name

    @visualize_model_state(VisualizationState.THINKING)
    @_record_llm_request_outcome
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
        token_stat_ticket = self.tokenStat.add_msgs(messages)

        first_byte_timeout, raise_on_first_byte_timeout = self._get_first_byte_timeout_config()

        response = self._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_first_byte_timeout,
        )
        self.tokenStat.wait(token_stat_ticket)
        full_content = OpenAIResponseAdapter.get_response_content(response)
        self.tokenStat.finalize_usage(
            self.get_response_usage(response),
            token_stat_ticket,
            full_content,
        )

        full_content = self.fix_response_content(rsp_obj=response, rsp_content=full_content)
        self.check_response_content(rsp_obj=response, rsp_content=full_content)

        self.send_content(full_content)
        self.tokenStat.print_token_stat()

        self._record_llm_response_event(response, is_stream=False)

        return (response, full_content)

    def iter_stream_with_first_byte_timeout(
        self,
        stream,
        first_byte_timeout=180,
        raise_on_timeout=False,
        create_timed_out=False,
    ):
        """Retain the stream first-byte timeout compatibility seam."""
        yield from super().iter_stream_with_first_byte_timeout(
            stream,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_timeout,
            create_timed_out=create_timed_out,
        )

    def _iter_stream_for_request_timing(self, stream, ticket):
        """Time only blocking provider iterator operations, not chunk processing.

        Thin wrapper around the provider-neutral helper in ``llm_control``.
        """
        return _iter_stream_for_request_timing(
            stream,
            ticket,
            resume=self._resume_llm_request,
            pause=self._pause_llm_request,
        )

    @visualize_model_state(VisualizationState.THINKING)
    @_record_llm_request_outcome
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
        token_stat_ticket = self.tokenStat.add_msgs(messages)

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

        usage = None
        usage_chunk_count = 0
        usage_details_chunk_count = 0
        cached_tokens_chunk_count = 0

        first_byte_ms = None

        stream_chunk_sample = env_tool.EnvReaderInstance.get(
            "TOPSAILAI_LLM_RESPONSE_EVENTS_STREAM_CHUNK_SAMPLE",
            default=0,
            formatter=int,
        )
        if stream_chunk_sample is None or stream_chunk_sample < 0:
            stream_chunk_sample = 0
        sampled_chunks = [] if stream_chunk_sample > 0 else None

        timing_ticket = _llm_request_timing_ticket.get()
        timed_response = self._iter_stream_for_request_timing(response, timing_ticket)
        for chunk in self.iter_stream_with_first_byte_timeout(
            timed_response,
            first_byte_timeout,
            raise_on_timeout=raise_on_first_byte_timeout,
            create_timed_out=create_timed_out,
        ):
            delta_obj = OpenAIResponseAdapter.get_stream_delta(chunk)
            try:
                delta_usage = self.get_response_usage(chunk)
                delta_prompt_tokens_details = None
                delta_cached_tokens = None
                if delta_usage is not None:
                    usage = delta_usage
                    usage_chunk_count += 1
                    delta_prompt_tokens_details = getattr(delta_usage, "prompt_tokens_details", None)
                    if delta_prompt_tokens_details is not None:
                        usage_details_chunk_count += 1
                        delta_cached_tokens = getattr(delta_prompt_tokens_details, "cached_tokens", None)
                        if delta_cached_tokens is not None:
                            cached_tokens_chunk_count += 1
                logger.debug(
                    "stream usage chunk: has_usage=%s has_prompt_tokens_details=%s cached_tokens=%r",
                    delta_usage is not None,
                    delta_prompt_tokens_details is not None,
                    delta_cached_tokens,
                )
            except Exception as e:
                logger.warning("failed to read streaming usage: %s", e, exc_info=True)
            if delta_obj is None:
                continue
            if sampled_chunks is not None and len(sampled_chunks) < stream_chunk_sample:
                try:
                    chunk_data = None
                    if hasattr(chunk, "to_dict"):
                        chunk_data = chunk.to_dict()
                    elif hasattr(chunk, "model_dump"):
                        chunk_data = chunk.model_dump()
                    else:
                        chunk_data = {"_repr": repr(chunk)}
                    sampled_chunks.append(chunk_data)
                except Exception:
                    pass


            # Record first-byte timing on the first chunk that carries content
            # or tool-call data. This measures the time from stream start to the
            # first useful response byte.
            if first_byte_ms is None:
                first_byte_ms = (time.monotonic() - stream_start_time) * 1000

            # Cooperative hard-interrupt check during streaming. The check is
            # throttled so it does not add I/O overhead on every chunk.
            try:
                agent = get_agent_object()
                if agent is not None and hasattr(agent, "_check_hard_interrupt"):
                    agent._check_hard_interrupt(throttle_stream=True)
            except HardInterruptError:
                # Re-raise immediately so the ReAct loop can stop cleanly.
                raise
            except Exception:
                # Any other problem with the interrupt check must not break
                # the streaming response.
                pass

            # content
            delta_content = OpenAIResponseAdapter.get_delta_content(delta_obj)
            if delta_content:
                full_content += delta_content
                self.send_content(delta_content)

            # tool_calls
            OpenAIResponseAdapter.merge_delta_tool_calls(
                full_tool_calls_dict,
                delta_obj,
            )
        # enf for chunk

        timing_ticket = _llm_request_timing_ticket.get()
        if timing_ticket is not None:
            self._finish_llm_request(timing_ticket)

        # Record first-byte timing for stream responses.
        if first_byte_ms is not None:
            self.tokenStat.add_first_byte(first_byte_ms)

        # Notify all content senders that the stream has finished so they can
        # emit a final newline or release any in-progress rendering state.
        for sender in self.content_senders:
            if hasattr(sender, "finish"):
                sender.finish()

        # generate tool_calls
        full_tool_calls_list = OpenAIResponseAdapter.build_tool_calls(
            full_tool_calls_dict,
        )

        if env_tool.is_debug_mode():
            print()

        self.tokenStat.wait(token_stat_ticket)
        final_prompt_tokens_details = (
            getattr(usage, "prompt_tokens_details", None)
            if usage is not None
            else None
        )
        final_cached_tokens = (
            getattr(final_prompt_tokens_details, "cached_tokens", None)
            if final_prompt_tokens_details is not None
            else None
        )
        logger.debug(
            "final streaming usage before TokenStat: prompt_tokens=%r completion_tokens=%r "
            "cached_tokens=%r usage_chunks=%s prompt_details_chunks=%s "
            "cached_value_chunks=%s",
            getattr(usage, "prompt_tokens", None) if usage is not None else None,
            getattr(usage, "completion_tokens", None) if usage is not None else None,
            final_cached_tokens,
            usage_chunk_count,
            usage_details_chunk_count,
            cached_tokens_chunk_count,
        )
        self.tokenStat.finalize_usage(usage, token_stat_ticket, full_content)

        full_content = full_content.strip()

        response_ccm = OpenAIResponseAdapter.build_assistant_message(
            full_content,
            full_tool_calls_list,
        )

        full_content = self.fix_response_content(rsp_obj=response_ccm, rsp_content=full_content)
        self.check_response_content(rsp_obj=response_ccm, rsp_content=full_content)
        self.tokenStat.print_token_stat()

        self._record_llm_response_event(response_ccm, is_stream=True, sampled_chunks=sampled_chunks)

        return (response_ccm, full_content)

    def chat(
            self, messages,
            for_raw=False,
            for_stream=False,
            for_response=False,
            tools=None,
            tool_choice="auto",
            retry_interaction_policy=None,
        ):
        """
        Main chat method with comprehensive error handling and retry logic.

        LLM retries stay inside this method and resend the same ``messages``
        with the same request options. They never retry ``ai_agent.run()`` or
        repeat Agent-loop message injection and tool execution.

        Args:
            messages (list): List of message dictionaries.
            for_raw (bool, optional): Return raw response content.
            for_stream (bool, optional): Use streaming mode.
            for_response (bool, optional): Return response object with content.
            tools (list, optional): List of available tools.
            tool_choice (str, optional): Tool choice strategy.
            retry_interaction_policy: Per-run LLM retry interaction policy.

        Raises:
            LLMBackToChatError: If an interactive user abandons this turn.
            LLMRetryExhaustedError: If bounded request retries are exhausted.
        """
        pending_responses = self._get_pending_native_tool_call_responses()
        if pending_responses:
            rsp_obj, rsp_content, sequence, total = pending_responses.popleft()
            logger.debug(
                "dequeued native tool-call response; %s pending",
                len(pending_responses),
            )
            print_info(f"Native tool call {sequence}/{total}")
            return self._return_chat_response(
                rsp_obj,
                rsp_content,
                messages,
                for_raw=for_raw,
                for_response=for_response,
            )

        policy = retry_interaction_policy or LLMRetryInteractionPolicy()
        prompt_allowed = policy.can_prompt() and thread_tool.is_main_thread()
        attempts_per_cycle = 18
        max_total_attempts = attempts_per_cycle * (
            policy.max_manual_retry_cycles + 1
        )
        manual_cycle_count = 0
        last_error = None
        retry_reason = "unknown"
        manual_retry_requested = False

        loop_attempts = max_total_attempts if prompt_allowed else attempts_per_cycle
        for total_attempt in range(1, loop_attempts + 1):
            attempt_in_cycle = (total_attempt - 1) % attempts_per_cycle + 1
            i = attempt_in_cycle - 1
            if attempt_in_cycle == 1:
                err_count_map = {}
                if total_attempt > 1:
                    exhausted_error = LLMRetryExhaustedError(
                        attempts=total_attempt - 1,
                        manual_cycle_count=manual_cycle_count,
                        last_error=last_error,
                        retry_reason=retry_reason,
                    )
                    action = _read_retry_exhaustion_action(
                        policy,
                        allow_retry=(
                            manual_cycle_count < policy.max_manual_retry_cycles
                        ),
                        warning_func=print_warning,
                    )
                    if action == "retry":
                        manual_cycle_count += 1
                    elif action == "back":
                        raise LLMBackToChatError(
                            attempts=total_attempt - 1,
                            manual_cycle_count=manual_cycle_count,
                            last_error=last_error,
                            retry_reason=retry_reason,
                        ) from last_error
                    else:
                        raise exhausted_error from last_error
            try:
                agent = get_agent_object()
                if agent is not None and hasattr(agent, "_check_hard_interrupt"):
                    agent._check_hard_interrupt()
            except HardInterruptError:
                raise
            except Exception:
                pass

            if attempt_in_cycle > 1:
                sec = 5 if manual_retry_requested else (i % attempts_per_cycle) * 5
                manual_retry_requested = False
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

                    _info["current_tokens"] = self.tokenStat.current_tokens
                    _info["cached_tokens"] = self.tokenStat.current_cached_tokens

                if for_raw:
                    return rsp_content

                (
                    rsp_obj,
                    rsp_content,
                    sequence,
                    total,
                ) = self._split_native_tool_call_response(
                    rsp_obj,
                    rsp_content,
                )
                if total > 1:
                    print_info(f"Native tool call {sequence}/{total}")
                return self._return_chat_response(
                    rsp_obj,
                    rsp_content,
                    messages,
                    for_response=for_response,
                )
            except KeyboardInterrupt:
                if not prompt_allowed:
                    raise
                if input_yes_or_no(
                        ">>> LLM Retry [yes/no] ", policy.input_func
                    ):
                    # This retries only the same LLM chat request. It does
                    # not restart the Agent loop or repeat any tool call.
                    manual_retry_requested = True
                    continue
                raise
            except JsonError as e:
                last_error = e
                retry_reason = "json"
                print_error(f"!!! [{i}] JsonError, {e}")
                continue
            except openai.RateLimitError as e:
                last_error = e
                retry_reason = "rate_limit"
                print_error(
                    f"!!! [{i}] RateLimitError, "
                    f"{self.model_config['api_key'][:7]}, {e}"
                )
                continue
            except TypeError as e:
                last_error = e
                retry_reason = "type_error"
                print_error(f"!!! [{i}] TypeError, {e}")
                continue
            except openai.InternalServerError as e:
                last_error = e
                retry_reason = "internal_server"
                print_error(f"!!! [{i}] InternalServerError, {e}")
                err_count_map["InternalServerError"] = (
                    err_count_map.get("InternalServerError", 0) + 1
                )
                if err_count_map["InternalServerError"] > 5:
                    self.rebuild_llm_models()
                continue
            except openai.APITimeoutError as e:
                last_error = e
                retry_reason = "timeout"
                print_error(f"!!! [{i}] APITimeoutError, {e}")
                continue
            except openai.APIConnectionError as e:
                last_error = e
                retry_reason = "connection"
                print_error(f"!!! [{i}] APIConnectionError, {e}")
                continue
            except openai.PermissionDeniedError as e:
                last_error = e
                retry_reason = "permission_denied"
                print_error(f"!!! [{i}] PermissionDeniedError, {e}")
                continue
            except openai.BadRequestError as e:
                last_error = e
                retry_reason = "bad_request"
                print_error(f"!!! [{i}] BadRequestError, {e}")
                e_str = str(e).lower()
                if "exceed" in e_str or "maximum context" in e_str:
                    raise

                marker = _match_non_retryable_bad_request(e_str)
                if marker:
                    raise openai.BadRequestError(
                        "Non-retryable request-shape 400 "
                        f"(matched marker: '{marker}'). The request payload is "
                        "malformed, most likely the Agent2LLM context contains an "
                        "unpaired assistant tool call or tool output after context "
                        "summarization or pruning; retrying cannot recover. "
                        f"Original error: {e}",
                        response=e.response,
                        body=e.body,
                    ) from e
                continue
            except (
                    httpx.ReadError,
                    httpcore.ReadError,
                    httpx.RemoteProtocolError,
                    httpx.ReadTimeout,
                    httpcore.ReadTimeout,
                ) as e:
                last_error = e
                retry_reason = "read_error"
                print_error(f"!!! [{i}] ReadError, {e}")
                continue
            except ModelServiceError as e:
                last_error = e
                retry_reason = (
                    "special_response"
                    if isinstance(e, LLMServiceSpecialResponseError)
                    else "model_service"
                )
                e_str = str(e).lower()
                if "token exceed" in e_str:
                    raise

                sec = 30
                if "bad_request" in e_str or "bad request" in e_str:
                    sec = 1
                if isinstance(e, LLMServiceSpecialResponseError):
                    sec = random.choice(
                        _LLM_SERVICE_SPECIAL_RESPONSE_SLEEP_SECONDS
                    )

                print_error(f"!!! [{i}] {LLM_KEYWORD_SERVICE}: {e}")
                print_error(f"blocking chat {sec}s ...")
                time.sleep(sec)
                continue
            except (HardInterruptError, LLMBackToChatError, LLMRetryExhaustedError):
                # These signals control a higher-level flow and must never
                # be mistaken for retryable provider failures.
                raise
            except (KeyError, Exception) as e:
                last_error = e
                retry_reason = "unknown"
                print_error(f"Some errors have occurred: [{e}]")
                logger.exception("some errors have occurred: %s", e)
                if prompt_allowed:
                    if input_yes_or_no(
                            ">>> LLM Retry [yes/no] ", policy.input_func
                        ):
                        # Continue this LLM chat request with the same
                        # messages; never retry the Agent loop here.
                        manual_retry_requested = True
                        continue
                    raise
                # Non-interactive callers must never block for input. The
                # same LLM chat request continues its bounded auto-retries.
                continue

        raise LLMRetryExhaustedError(
            attempts=loop_attempts,
            manual_cycle_count=manual_cycle_count,
            last_error=last_error,
            retry_reason=retry_reason,
        ) from last_error
