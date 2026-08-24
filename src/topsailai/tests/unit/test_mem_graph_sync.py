"""Unit tests for the external append-only mem-graph consumer."""

import json
import os
import tempfile
from unittest import TestCase, mock

from topsailai.scripts import mem_graph_sync
from topsailai.scripts import mem_graph_sync_outbox as outbox
from topsailai.tools.memory_tool_utils import memory_stat


class FakeTransport:
    """Record consumer operations and optionally fail selected calls."""

    def __init__(self, *, readiness_failures=0, create_failures=0):
        self.readiness_failures = readiness_failures
        self.create_failures = create_failures
        self.readiness_calls = 0
        self.created = []

    def readiness(self):
        """Simulate readiness with a bounded number of transient failures."""
        self.readiness_calls += 1
        if self.readiness_calls <= self.readiness_failures:
            raise mem_graph_sync.SyncError("unavailable")

    def create_snapshot(self, event):
        """Record each append-only create call without any read/update API."""
        if self.create_failures:
            self.create_failures -= 1
            raise mem_graph_sync.SyncError("create failed")
        self.created.append(dict(event))


class TestMemGraphSync(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.event = {
            "schema_version": 1,
            "event": "create",
            "memory_id": "20260824150000.example.md",
            "title": "Example",
            "content": "snapshot body",
            "memory_file": os.path.join(self.temp_dir.name, "story", "example.md"),
            "workspace": self.temp_dir.name,
            "timestamp": "2026-08-24 15:00:00 +08:00",
            "version": 1,
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validate_event_accepts_create_update_and_rejects_delete(self):
        self.assertIs(mem_graph_sync.validate_event(self.event), self.event)
        updated = {**self.event, "event": "update", "version": 2}
        self.assertIs(mem_graph_sync.validate_event(updated), updated)
        with self.assertRaisesRegex(mem_graph_sync.SyncError, "unsupported"):
            mem_graph_sync.validate_event({**self.event, "event": "delete"})

    def test_create_and_update_each_append_a_brand_new_snapshot(self):
        transport = FakeTransport()
        updated = {**self.event, "event": "update", "version": 2, "content": "new body"}

        self.assertTrue(mem_graph_sync.process_event(self.event, transport, sleep=mock.Mock()))
        self.assertTrue(mem_graph_sync.process_event(updated, transport, sleep=mock.Mock()))

        self.assertEqual(transport.created, [self.event, updated])
        stat = memory_stat.read_memory_stat(self.temp_dir.name, self.event["memory_id"])
        self.assertTrue(stat["synced"])
        self.assertIsNone(stat["last_sync_error"])
        self.assertEqual(stat["last_synced_version"], 2)
        self.assertEqual(
            stat["last_synced_content_digest"],
            memory_stat.get_content_digest("new body"),
        )

    def test_readiness_failure_queues_event_and_records_failure(self):
        transport = FakeTransport(readiness_failures=10)

        self.assertFalse(mem_graph_sync.process_event(self.event, transport, sleep=mock.Mock()))

        self.assertEqual(outbox.read(self.temp_dir.name), [self.event])
        stat = memory_stat.read_memory_stat(self.temp_dir.name, self.event["memory_id"])
        self.assertFalse(stat["synced"])
        self.assertEqual(stat["last_sync_error"], "unavailable")
        self.assertEqual(transport.created, [])

    def test_transient_failure_retries_with_lightweight_backoff(self):
        transport = FakeTransport(create_failures=2)
        sleep = mock.Mock()

        self.assertTrue(mem_graph_sync.process_event(self.event, transport, sleep=sleep))

        self.assertEqual(transport.created, [self.event])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.25, 0.5])

    def test_retry_outbox_consumes_success_and_retains_failure(self):
        second = {**self.event, "memory_id": "second.md", "title": "Second"}
        outbox.enqueue(self.temp_dir.name, self.event)
        outbox.enqueue(self.temp_dir.name, second)
        transport = FakeTransport(create_failures=3)

        succeeded = mem_graph_sync.retry_outbox(
            self.temp_dir.name, transport, sleep=mock.Mock()
        )

        self.assertEqual(succeeded, 1)
        self.assertEqual(outbox.read(self.temp_dir.name), [self.event])
        self.assertEqual(transport.created, [second])

    def test_live_transport_uses_personal_create_and_default_account_header(self):
        """Authenticated creates use the default account when configuration is absent."""
        responses = []

        class Response:
            """Provide a successful response-envelope context manager."""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"code":0,"message":"success","data":{}}'

        def fake_urlopen(request, timeout):
            responses.append((request, timeout))
            return Response()

        transport = mem_graph_sync.MemGraphTransport("http://example.test", 4)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            mem_graph_sync, "urlopen", side_effect=fake_urlopen
        ):
            transport.readiness()
            transport.create_snapshot(self.event)

        readiness_request, create_request = responses[0][0], responses[1][0]
        self.assertNotIn("X-external-user-id", readiness_request.headers)
        self.assertEqual(create_request.headers["X-external-user-id"], "test")
        body = json.loads(create_request.data)
        self.assertEqual(body["scope_ref"], "personal")
        self.assertIn("#version=1#event=create", body["source_reference"])
        self.assertEqual(create_request.method, "POST")

    def test_live_transport_trims_trailing_content_and_rejects_empty_content(self):
        """Outbound content is normalized without mutating the source event."""
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"code":0}'

        def capture_request(request, timeout):
            del timeout
            requests.append(request)
            return Response()

        event = {**self.event, "content": "snapshot body \n\t"}
        transport = mem_graph_sync.MemGraphTransport("http://example.test", 4)
        with mock.patch.object(
            mem_graph_sync, "urlopen", side_effect=capture_request
        ):
            transport.create_snapshot(event)

        self.assertEqual(json.loads(requests[0].data)["content"], "snapshot body")
        self.assertEqual(event["content"], "snapshot body \n\t")
        with self.assertRaisesRegex(
            mem_graph_sync.SyncError, "invalid mem-graph content"
        ):
            transport.create_snapshot({**self.event, "content": " \n\t"})

    def test_outbox_replays_trailing_content_and_records_original_digest(self):
        """A legacy queued event converges while stat tracks the local snapshot."""
        event = {**self.event, "content": "snapshot body\n"}
        outbox.enqueue(self.temp_dir.name, event)
        transport = mem_graph_sync.MemGraphTransport("http://example.test", 4)

        with mock.patch.object(transport, "readiness"), mock.patch.object(
            transport, "_request"
        ) as request:
            succeeded = mem_graph_sync.retry_outbox(
                self.temp_dir.name, transport, sleep=mock.Mock()
            )

        self.assertEqual(succeeded, 1)
        self.assertEqual(outbox.read(self.temp_dir.name), [])
        self.assertEqual(request.call_args.kwargs["body"]["content"], "snapshot body")
        stat = memory_stat.read_memory_stat(self.temp_dir.name, event["memory_id"])
        self.assertEqual(
            stat["last_synced_content_digest"],
            memory_stat.get_content_digest("snapshot body\n"),
        )

    def test_outbox_is_deduplicated_and_bounded_by_entry_count(self):
        with mock.patch.dict(os.environ, {"TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_ENTRIES": "2"}):
            outbox.enqueue(self.temp_dir.name, self.event)
            outbox.enqueue(self.temp_dir.name, self.event)
            outbox.enqueue(self.temp_dir.name, {**self.event, "memory_id": "second.md"})
            outbox.enqueue(self.temp_dir.name, {**self.event, "memory_id": "third.md"})

        self.assertEqual(
            [event["memory_id"] for event in outbox.read(self.temp_dir.name)],
            ["second.md", "third.md"],
        )


class TestMemGraphSyncBoundaries(TestCase):
    """Cover consumer validation, transport, configuration, and entry boundaries."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.event = {
            "schema_version": 1,
            "event": "create",
            "memory_id": "boundary.md",
            "title": "Boundary",
            "content": "content",
            "memory_file": os.path.join(self.temp_dir.name, "story", "boundary.md"),
            "workspace": self.temp_dir.name,
            "timestamp": "2026-08-24 15:00:00 +08:00",
            "version": 1,
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validate_event_rejects_shape_version_and_empty_fields(self):
        """Malformed contract shapes, revisions, and strings are rejected."""
        for event in (None, {}, {**self.event, "version": True}, {**self.event, "version": 0}):
            with self.assertRaises(mem_graph_sync.SyncError):
                mem_graph_sync.validate_event(event)
        with self.assertRaisesRegex(mem_graph_sync.SyncError, "field: title"):
            mem_graph_sync.validate_event({**self.event, "title": ""})

    def test_live_transport_wraps_io_and_rejects_bad_envelope(self):
        """Transport failures and non-success envelopes become safe SyncError values."""
        transport = mem_graph_sync.MemGraphTransport("http://example.test/", 2)
        self.assertEqual(transport.base_url, "http://example.test")
        with mock.patch.object(
            mem_graph_sync, "urlopen", side_effect=mem_graph_sync.URLError("down")
        ), self.assertRaisesRegex(mem_graph_sync.SyncError, "request failed"):
            transport.readiness()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"code":1}'

        with mock.patch.object(mem_graph_sync, "urlopen", return_value=Response()), \
             self.assertRaisesRegex(mem_graph_sync.SyncError, "unsuccessful"):
            transport.readiness()

    def test_http_validation_error_is_classified_without_reading_response_body(self):
        """Validation failures expose a safe category and no provider payload."""
        response_body = mock.Mock()
        error = mem_graph_sync.HTTPError(
            "http://example.test/v1/memories",
            422,
            "unprocessable",
            hdrs=None,
            fp=response_body,
        )
        transport = mem_graph_sync.MemGraphTransport("http://example.test", 2)

        with mock.patch.object(mem_graph_sync, "urlopen", side_effect=error), \
             self.assertRaisesRegex(
                 mem_graph_sync.SyncError,
                 "^mem-graph request failed: validation error$",
             ):
            transport.create_snapshot(self.event)

        response_body.read.assert_not_called()

    def test_retry_fallbacks_and_exhaustion(self):
        """Invalid retry settings fall back and persistent failure is re-raised."""
        operation = mock.Mock(side_effect=mem_graph_sync.SyncError("still down"))
        sleep = mock.Mock()
        with mock.patch.dict(
            os.environ,
            {
                "TOPSAILAI_MEMORY_SYNC_RETRY_ATTEMPTS": "invalid",
                "TOPSAILAI_MEMORY_SYNC_BACKOFF_SECONDS": "-1",
            },
        ), self.assertRaisesRegex(mem_graph_sync.SyncError, "still down"):
            mem_graph_sync._retry(operation, sleep)
        self.assertEqual(operation.call_count, mem_graph_sync.DEFAULT_RETRY_ATTEMPTS)

    def test_record_sync_is_fail_open(self):
        """Stat persistence errors never replace the primary sync result."""
        with mock.patch.object(
            mem_graph_sync.memory_stat,
            "record_memory_sync",
            side_effect=OSError("read only"),
        ):
            mem_graph_sync._record_sync(self.event, synced=True)

    def test_script_env_loads_named_file_without_overriding_process(self):
        """The script-specific dotenv file fills only missing process values."""
        env_file = mem_graph_sync.Path(self.temp_dir.name) / "mem_graph_sync.env"
        env_file.write_text(
            "FILE_ONLY=from-file\nPROCESS_WINS=from-file\n", encoding="utf-8"
        )

        with mock.patch.dict(os.environ, {"PROCESS_WINS": "from-process"}, clear=True):
            mem_graph_sync._load_script_env(env_file)
            self.assertEqual(os.environ["FILE_ONLY"], "from-file")
            self.assertEqual(os.environ["PROCESS_WINS"], "from-process")

    def test_external_user_id_honors_primary_compatible_and_default_precedence(self):
        """Account identity resolves from the primary key, compatible key, then default."""
        primary = mem_graph_sync.EXTERNAL_USER_ID_ENV
        compatible = mem_graph_sync.EXTERNAL_USER_ID_COMPAT_ENV
        env_file = mem_graph_sync.Path(self.temp_dir.name) / "mem_graph_sync.env"
        env_file.write_text(f"{compatible}=from-file\n", encoding="utf-8")

        with mock.patch.dict(os.environ, {}, clear=True):
            mem_graph_sync._load_script_env(env_file)
            self.assertEqual(mem_graph_sync._external_user_id(), "from-file")
        with mock.patch.dict(
            os.environ,
            {primary: "from-primary", compatible: "from-compatible"},
            clear=True,
        ):
            mem_graph_sync._load_script_env(env_file)
            self.assertEqual(mem_graph_sync._external_user_id(), "from-primary")
        with mock.patch.dict(os.environ, {compatible: "from-process"}, clear=True):
            mem_graph_sync._load_script_env(env_file)
            self.assertEqual(mem_graph_sync._external_user_id(), "from-process")
        for environment in ({}, {primary: "", compatible: ""}, {primary: "   ", compatible: "   "}):
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(mem_graph_sync._external_user_id(), "test")

    def test_script_env_ignores_missing_file_and_warns_on_loader_failure(self):
        """A missing dotenv file is harmless and loader failures are isolated."""
        env_file = mem_graph_sync.Path(self.temp_dir.name) / "mem_graph_sync.env"
        mem_graph_sync._load_script_env(env_file)
        env_file.write_text("BROKEN=value\n", encoding="utf-8")

        with mock.patch.object(
            mem_graph_sync, "load_dotenv", side_effect=ValueError("malformed")
        ), self.assertLogs(mem_graph_sync.logger, level="WARNING") as captured:
            mem_graph_sync._load_script_env(env_file)

        self.assertIn("failed to load script environment file", captured.output[0])

    def test_build_transport_uses_boundary_configuration(self):
        """Transport construction resolves URL and timeout at the script boundary."""
        with mock.patch.dict(
            os.environ,
            {
                "MEMGRAPH_API_BASE_URL": "http://configured.test/",
                "TOPSAILAI_MEMORY_SYNC_REQUEST_TIMEOUT": "7.5",
            },
        ):
            transport = mem_graph_sync.build_transport()
        self.assertEqual(transport.base_url, "http://configured.test")
        self.assertEqual(transport.timeout_seconds, 7.5)

    def test_port_check_uses_endpoint_port_and_short_timeout(self):
        """The fast probe derives host and port and closes its TCP connection."""
        connection = mock.Mock()
        connect = mock.Mock(return_value=connection)

        mem_graph_sync.check_port("https://example.test/path", 0.4, connect=connect)

        connect.assert_called_once_with(("example.test", 443), timeout=0.4)
        connection.close.assert_called_once_with()

    def test_port_check_rejects_invalid_and_unreachable_endpoints(self):
        """Invalid endpoints and connection failures become clear SyncError values."""
        with self.assertRaisesRegex(mem_graph_sync.SyncError, "invalid"):
            mem_graph_sync.check_port("not-an-endpoint", 0.5, connect=mock.Mock())
        with self.assertRaisesRegex(mem_graph_sync.SyncError, "unreachable: host.test:8004"):
            mem_graph_sync.check_port(
                "http://host.test:8004",
                0.5,
                connect=mock.Mock(side_effect=OSError("refused")),
            )

    def test_main_handles_invalid_success_queued_and_unreachable_port(self):
        """The CLI boundary maps invalid, synced, queued, and fast-fail outcomes."""
        with mock.patch.object(mem_graph_sync.sys, "stdin", mock.Mock()), \
             mock.patch.object(mem_graph_sync.json, "load", side_effect=ValueError("bad")):
            self.assertEqual(mem_graph_sync.main(), 2)

        with mock.patch.object(mem_graph_sync.sys, "stdin", mock.Mock()), \
             mock.patch.object(mem_graph_sync.json, "load", return_value=self.event), \
             mock.patch.object(mem_graph_sync, "build_transport", return_value=mock.Mock()), \
             mock.patch.object(mem_graph_sync, "check_port"), \
             mock.patch.object(mem_graph_sync, "retry_outbox") as retry_pending, \
             mock.patch.object(mem_graph_sync, "process_event", return_value=True):
            self.assertEqual(mem_graph_sync.main(), 0)
            retry_pending.assert_called_once()

        with mock.patch.object(mem_graph_sync.sys, "stdin", mock.Mock()), \
             mock.patch.object(mem_graph_sync.json, "load", return_value=self.event), \
             mock.patch.object(mem_graph_sync, "build_transport", return_value=mock.Mock()), \
             mock.patch.object(mem_graph_sync, "check_port"), \
             mock.patch.object(mem_graph_sync, "retry_outbox"), \
             mock.patch.object(mem_graph_sync, "process_event", return_value=False):
            self.assertEqual(mem_graph_sync.main(), 1)

        with mock.patch.object(mem_graph_sync.sys, "stdin", mock.Mock()), \
             mock.patch.object(mem_graph_sync.json, "load", return_value=self.event), \
             mock.patch.object(mem_graph_sync, "build_transport", return_value=mock.Mock()), \
             mock.patch.object(
                 mem_graph_sync,
                 "check_port",
                 side_effect=mem_graph_sync.SyncError("mem-graph port is unreachable"),
             ), \
             mock.patch.object(mem_graph_sync, "retry_outbox") as retry_pending, \
             mock.patch.object(mem_graph_sync.outbox, "enqueue") as enqueue:
            self.assertEqual(mem_graph_sync.main(), 1)
            retry_pending.assert_not_called()
            enqueue.assert_called_once_with(self.event["workspace"], self.event)

    def test_outbox_invalid_limits_corrupt_records_and_byte_bound(self):
        """Outbox falls back on bad limits, skips corruption, and drops oversized data."""
        path = outbox.get_outbox_file(self.temp_dir.name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("not-json\n")
            stream.write(json.dumps(self.event) + "\n")
        self.assertEqual(outbox.read(self.temp_dir.name), [self.event])

        with mock.patch.dict(
            os.environ,
            {
                "TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_ENTRIES": "invalid",
                "TOPSAILAI_MEMORY_SYNC_OUTBOX_MAX_BYTES": "10",
            },
        ):
            outbox.replace(self.temp_dir.name, [self.event])
        self.assertEqual(outbox.read(self.temp_dir.name), [])

    def test_outbox_write_removes_leftover_temp_file(self):
        """A failed atomic replacement cleans its exact temporary file."""
        path = outbox.get_outbox_file(self.temp_dir.name)
        real_replace = outbox.os.replace
        with mock.patch.object(outbox.os, "replace", side_effect=OSError("replace failed")), \
             self.assertRaisesRegex(OSError, "replace failed"):
            outbox._write_unlocked(path, [self.event])
        self.assertEqual(
            [name for name in os.listdir(os.path.dirname(path)) if name.endswith(".tmp")],
            [],
        )
        self.assertIsNotNone(real_replace)
