"""Provider-neutral orchestration for complete and streaming LLM calls."""

from __future__ import annotations

import time


class LLMCallMixin:
    """Coordinate LLM calls through provider-owned adaptation hooks."""

    def call_llm_model(self, messages, tools=None, tool_choice="auto"):
        """Call a provider and return its response with normalized content."""
        token_stat_ticket = self.tokenStat.add_msgs(messages)
        first_byte_timeout, raise_on_timeout = self._get_first_byte_timeout_config()

        response = self._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=False,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_timeout,
        )
        self.tokenStat.wait(token_stat_ticket)
        full_content = self._extract_response_content(response)
        self.tokenStat.finalize_usage(
            self.get_response_usage(response),
            token_stat_ticket,
            full_content,
        )

        full_content = self.fix_response_content(
            rsp_obj=response,
            rsp_content=full_content,
        )
        self.check_response_content(rsp_obj=response, rsp_content=full_content)
        self.send_content(full_content)
        self.tokenStat.print_token_stat()
        self._record_llm_response_event(response, is_stream=False)
        return response, full_content

    def call_llm_model_by_stream(self, messages, tools=None, tool_choice="auto"):
        """Call a provider stream and return its reconstructed response and content."""
        token_stat_ticket = self.tokenStat.add_msgs(messages)
        first_byte_timeout, raise_on_timeout = self._get_first_byte_timeout_config()
        stream_start_time = time.monotonic()

        response, create_timed_out = self._create_with_first_byte_timeout(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=True,
            first_byte_timeout=first_byte_timeout,
            raise_on_timeout=raise_on_timeout,
        )

        full_content = ""
        accumulated_calls = {}
        usage = None
        usage_diagnostics = {}
        first_byte_ms = None
        sample_limit = self._get_stream_chunk_sample_limit()
        sampled_chunks = [] if sample_limit > 0 else None

        timing_ticket = self._get_llm_request_timing_ticket()
        timed_response = self._iter_stream_for_request_timing(response, timing_ticket)
        for chunk in self.iter_stream_with_first_byte_timeout(
            timed_response,
            first_byte_timeout,
            raise_on_timeout=raise_on_timeout,
            create_timed_out=create_timed_out,
        ):
            stream_part = self._extract_stream_part(chunk)
            try:
                current_usage = self.get_response_usage(chunk)
                if current_usage is not None:
                    usage = current_usage
                self._observe_stream_usage(current_usage, usage_diagnostics)
            except Exception as error:
                self._warn_stream_usage_error(error)

            if stream_part is None:
                continue
            if sampled_chunks is not None and len(sampled_chunks) < sample_limit:
                try:
                    sampled_chunks.append(self._serialize_stream_chunk(chunk))
                except Exception:
                    pass

            if first_byte_ms is None:
                first_byte_ms = (time.monotonic() - stream_start_time) * 1000

            self._check_stream_interrupt()
            content_part = self._extract_stream_content(stream_part)
            if content_part:
                full_content += content_part
                self.send_content(content_part)
            self._merge_stream_calls(accumulated_calls, stream_part)

        timing_ticket = self._get_llm_request_timing_ticket()
        if timing_ticket is not None:
            self._finish_llm_request(timing_ticket)
        if first_byte_ms is not None:
            self.tokenStat.add_first_byte(first_byte_ms)

        for sender in self.content_senders:
            if hasattr(sender, "finish"):
                sender.finish()

        completed_calls = self._build_stream_calls(accumulated_calls)
        self._finish_stream_debug_output()
        self.tokenStat.wait(token_stat_ticket)
        self._log_final_stream_usage(usage, usage_diagnostics)
        self.tokenStat.finalize_usage(usage, token_stat_ticket, full_content)

        full_content = full_content.strip()
        response_object = self._build_stream_response(full_content, completed_calls)
        full_content = self.fix_response_content(
            rsp_obj=response_object,
            rsp_content=full_content,
        )
        self.check_response_content(
            rsp_obj=response_object,
            rsp_content=full_content,
        )
        self.tokenStat.print_token_stat()
        self._record_llm_response_event(
            response_object,
            is_stream=True,
            sampled_chunks=sampled_chunks,
        )
        return response_object, full_content

    def _extract_response_content(self, response):
        """Extract text from one complete provider response."""
        raise NotImplementedError

    def _extract_stream_part(self, chunk):
        """Extract one useful provider-owned stream part."""
        raise NotImplementedError

    def _extract_stream_content(self, stream_part):
        """Extract text from one provider-owned stream part."""
        raise NotImplementedError

    def _merge_stream_calls(self, accumulated_calls, stream_part):
        """Merge provider-owned streamed calls into neutral accumulation state."""
        raise NotImplementedError

    def _build_stream_calls(self, accumulated_calls):
        """Build completed provider call objects from accumulation state."""
        raise NotImplementedError

    def _build_stream_response(self, content, completed_calls):
        """Build the provider response object returned to existing callers."""
        raise NotImplementedError
