"""Provider-neutral pending-response handling for native tool calls."""

from collections import deque


class NativeToolCallResponseMixin:
    """Split native tool calls and retain pending responses in FIFO order."""

    def _get_pending_native_tool_call_responses(self):
        """Return the lazily initialized per-model pending-response FIFO."""
        queue = getattr(self, "_pending_native_tool_call_responses", None)
        if queue is None:
            queue = deque()
            self._pending_native_tool_call_responses = queue
        return queue

    def clear_pending_native_tool_call_responses(self):
        """Discard pending responses without replacing the authoritative FIFO."""
        queue = self._get_pending_native_tool_call_responses()
        pending_count = len(queue)
        queue.clear()
        if pending_count:
            self._on_native_tool_call_responses_cleared(pending_count)

    def _split_native_tool_call_response(self, rsp_obj, rsp_content):
        """Split a multi-tool-call response into ordered single-call responses."""
        rsp_msg = self.get_response_message(rsp_obj)
        tool_calls = getattr(rsp_msg, "tool_calls", None) or []
        if len(tool_calls) <= 1:
            return rsp_obj, rsp_content, 1, 1

        total_tool_calls = len(tool_calls)
        responses = []
        for index, tool_call in enumerate(tool_calls):
            synthetic_content = rsp_content if index == 0 else ""
            synthetic_rsp_msg = self._build_single_native_tool_call_response(
                content=synthetic_content,
                tool_call=tool_call,
            )
            synthetic_content = self.fix_response_content(
                rsp_obj=synthetic_rsp_msg,
                rsp_content=synthetic_content,
            )
            responses.append((
                synthetic_rsp_msg,
                synthetic_content,
                index + 1,
                total_tool_calls,
            ))

        queue = self._get_pending_native_tool_call_responses()
        queue.extend(responses[1:])
        self._on_native_tool_call_response_split(total_tool_calls)
        return responses[0]

    def _build_single_native_tool_call_response(self, *, content, tool_call):
        """Build one provider response containing exactly one native tool call."""
        raise NotImplementedError

    def _on_native_tool_call_responses_cleared(self, pending_count):
        """Observe cleanup of pending native tool-call responses."""

    def _on_native_tool_call_response_split(self, total_tool_calls):
        """Observe splitting of one native multi-tool-call response."""
