"""Unit coverage for opt-in complete and post-first-item delays."""

import threading

from tests.unit.test_topsailai_llm_mock_server_timing import _request, running_server, _message


def test_after_first_chunk_delay_is_released_by_request_owner():
    """A post-first-item delay preserves the first decoded SSE entry."""
    with running_server(
        stream_chunks=("", "answer"),
        after_first_chunk_delays=(30.0,),
    ) as (server, base_url):
        result = []
        worker = threading.Thread(
            target=lambda: result.append(_request(base_url, [_message("user", "x")])),
        )
        worker.start()
        assert server.lifecycle_capture.wait_for_request(1, 3)
        assert server.lifecycle_capture.wait_for_phase(1, "after_first_chunk", 3)
        handle = server.lifecycle_capture.request_handle(1)
        assert handle.record["first_item_sent"] is True
        handle.release_delay()
        worker.join(5)
        assert not worker.is_alive()
        assert result and result[0][0] == 200


def test_complete_response_delay_is_opt_in_and_bounded():
    """A complete response delay uses the same release mechanism."""
    with running_server(complete_response_delays=(30.0,)) as (server, base_url):
        result = []
        worker = threading.Thread(
            target=lambda: result.append(_request(base_url, [_message("user", "x")], stream=False)),
        )
        worker.start()
        assert server.lifecycle_capture.wait_for_request(1, 3)
        assert server.lifecycle_capture.wait_for_phase(1, "complete_response", 3)
        server.lifecycle_capture.request_handle(1).release_delay()
        worker.join(5)
        assert not worker.is_alive()
        assert result and result[0][0] == 200
