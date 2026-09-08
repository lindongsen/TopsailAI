"""Provider-neutral first-byte timeout orchestration."""

import threading
import time


class FirstByteTimeoutMixin:
    """Coordinate request creation and stream first-item timeout handling."""

    def _create_with_first_byte_timeout(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        stream=False,
        first_byte_timeout=180,
        raise_on_timeout=False,
    ):
        """Create a provider response while monitoring time to first result."""
        params = self._build_first_byte_request_parameters(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
        )
        if first_byte_timeout is None or first_byte_timeout <= 0:
            return self._create_without_first_byte_timeout(params, stream=stream)

        result = [None]
        first_exc = [None]
        timing_ticket = [None]
        ticket_started = threading.Event()
        got_result = threading.Event()

        def create():
            """Run one provider attempt and publish its result and timing ticket."""
            ticket = None
            try:
                ticket = self._start_first_byte_request()
                timing_ticket[0] = ticket
                ticket_started.set()
                result[0] = self._create_first_byte_response(params)
                self._complete_first_byte_request(ticket, stream=stream)
            except BaseException as error:
                if ticket is not None:
                    self._finish_first_byte_request(ticket)
                first_exc[0] = error
            finally:
                ticket_started.set()
                got_result.set()

        start_time = time.monotonic()
        threading.Thread(target=create, daemon=True).start()
        ticket_started.wait()
        if timing_ticket[0] is not None:
            self._publish_first_byte_request_ticket(timing_ticket[0])

        timed_out = not got_result.wait(timeout=first_byte_timeout)
        elapsed = time.monotonic() - start_time
        if timed_out:
            self._log_first_byte_timeout(elapsed, first_byte_timeout)
            if raise_on_timeout:
                raise self._make_first_byte_timeout_error(first_byte_timeout)
            got_result.wait()
            if first_exc[0] is not None:
                raise first_exc[0]
            return self._format_first_byte_create_result(
                result[0], stream=stream, create_timed_out=True
            )

        if first_exc[0] is not None:
            raise first_exc[0]
        return self._format_first_byte_create_result(
            result[0], stream=stream, create_timed_out=False
        )

    def iter_stream_with_first_byte_timeout(
        self,
        stream,
        first_byte_timeout=180,
        raise_on_timeout=False,
        create_timed_out=False,
    ):
        """Yield a stream while applying a timeout only to its first item."""
        yield from self._iter_first_byte_timeout(
            stream,
            first_byte_timeout,
            raise_on_timeout,
            create_timed_out,
            on_timeout=self._log_first_byte_timeout,
            make_timeout_error=self._make_first_byte_timeout_error,
        )

    def _iter_first_byte_timeout(self, stream, *args, **kwargs):
        """Apply stream timeout behavior through the host adapter."""
        return iter_with_first_byte_timeout(stream, *args, **kwargs)

    def _create_without_first_byte_timeout(self, params, *, stream):
        """Run an unmonitored provider create attempt with timing accounting."""
        ticket = self._start_first_byte_request()
        self._publish_first_byte_request_ticket(ticket)
        try:
            response = self._create_first_byte_response(params)
        except BaseException:
            self._finish_first_byte_request(ticket)
            raise
        self._complete_first_byte_request(ticket, stream=stream)
        return self._format_first_byte_create_result(
            response, stream=stream, create_timed_out=False
        )

    @staticmethod
    def _format_first_byte_create_result(response, *, stream, create_timed_out):
        """Preserve the established stream and non-stream return shapes."""
        if stream:
            return response, create_timed_out
        return response

    def _build_first_byte_request_parameters(
        self, messages, *, tools, tool_choice, stream
    ):
        """Build provider parameters through the host adapter."""
        raise NotImplementedError

    def _create_first_byte_response(self, params):
        """Execute provider creation through the host adapter."""
        raise NotImplementedError

    def _start_first_byte_request(self):
        """Start request timing through the host adapter."""
        raise NotImplementedError

    def _pause_first_byte_request(self, ticket):
        """Pause request timing through the host adapter."""
        raise NotImplementedError

    def _finish_first_byte_request(self, ticket):
        """Finish request timing through the host adapter."""
        raise NotImplementedError

    def _publish_first_byte_request_ticket(self, ticket):
        """Publish a request ticket through the host adapter."""
        raise NotImplementedError

    def _complete_first_byte_request(self, ticket, *, stream):
        """Pause a stream request or finish a non-stream request."""
        if stream:
            self._pause_first_byte_request(ticket)
            return
        self._finish_first_byte_request(ticket)


def iter_with_first_byte_timeout(
    stream,
    first_byte_timeout=180,
    raise_on_timeout=False,
    create_timed_out=False,
    *,
    on_timeout,
    make_timeout_error,
):
    """Yield a stream while applying a timeout only to its first item."""
    if first_byte_timeout is None or first_byte_timeout <= 0:
        yield from stream
        return

    first_item = [None]
    first_exception = [None]
    got_result = threading.Event()

    def fetch_first():
        """Fetch the first item in a daemon thread and publish its outcome."""
        try:
            first_item[0] = next(stream)
        except StopIteration:
            pass
        except Exception as error:
            first_exception[0] = error
        finally:
            got_result.set()

    start_time = time.monotonic()
    threading.Thread(target=fetch_first, daemon=True).start()
    timed_out = not got_result.wait(timeout=first_byte_timeout)
    elapsed = time.monotonic() - start_time

    if timed_out:
        if hasattr(stream, "close"):
            try:
                stream.close()
            except Exception:
                pass
        if not create_timed_out:
            on_timeout(elapsed, first_byte_timeout)
        if raise_on_timeout:
            raise make_timeout_error(first_byte_timeout)
        return

    if first_exception[0] is not None:
        raise first_exception[0]
    if first_item[0] is None:
        return
    if elapsed > first_byte_timeout and not create_timed_out:
        on_timeout(elapsed, first_byte_timeout)

    yield first_item[0]
    yield from stream
