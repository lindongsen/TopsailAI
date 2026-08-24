#!/usr/bin/env python3
"""Best-effort append-only story-memory consumer for Mem Graph."""

import hashlib
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_ENV_FILE = SCRIPT_DIR / (Path(__file__).stem + ".env")


def _load_script_env(env_file: Path = SCRIPT_ENV_FILE) -> None:
    """Load the script-specific dotenv file without overriding process values."""
    if not env_file.is_file():
        return
    try:
        load_dotenv(env_file, override=False)
    except Exception as error:
        logger.warning("failed to load script environment file %s: %s", env_file, error)


_load_script_env()

PROJECT_DIR = str(SCRIPT_DIR.parent)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from topsailai.scripts import mem_graph_sync_outbox as outbox
from topsailai.tools.memory_tool_utils import memory_stat

# This identifies the account; it is not a per-memory or per-node key.
EXTERNAL_USER_ID_ENV = "TOPSAILAI_MEMORY_SYNC_EXTERNAL_USER_ID"
EXTERNAL_USER_ID_COMPAT_ENV = "EXTERNAL_USER_ID"
DEFAULT_EXTERNAL_USER_ID = "test"


def _external_user_id() -> str:
    """Resolve the account identity from primary, compatible, or default configuration."""
    primary = os.environ.get(EXTERNAL_USER_ID_ENV, "").strip()
    compatible = os.environ.get(EXTERNAL_USER_ID_COMPAT_ENV, "").strip()
    return primary or compatible or DEFAULT_EXTERNAL_USER_ID


SUPPORTED_EVENTS = {"create", "update"}
REQUIRED_FIELDS = {
    "schema_version",
    "event",
    "memory_id",
    "title",
    "content",
    "memory_file",
    "workspace",
    "timestamp",
    "version",
}
DEFAULT_BASE_URL = "http://localhost:8004"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_PORT_CHECK_ENABLED = True
DEFAULT_PORT_CHECK_TIMEOUT_SECONDS = 0.5
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.25


class SyncError(RuntimeError):
    """Report a safe consumer failure suitable for stat observability."""


class MemGraphTransport:
    """Send the two bounded REST operations needed by this consumer."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        """Store a normalized endpoint and positive request timeout."""
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def readiness(self) -> None:
        """Raise SyncError unless the public readiness endpoint succeeds."""
        self._request("GET", "/health/ready", authenticated=False)

    def create_snapshot(self, event: dict) -> None:
        """Create one new personal memory node without reading old nodes."""
        body = {
            "memory_class": "episodic",
            "title": event["title"],
            "content": event["content"],
            "source_kind": "topsailai-story-memory",
            "source_reference": _source_reference(event),
            "sensitivity": "normal",
            "effective_time_ms": None,
            "expiry_ms": None,
            "scope_ref": "personal",
        }
        self._request(
            "POST",
            "/v1/memories",
            body=body,
            authenticated=True,
            idempotency_key=_idempotency_key(event),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        authenticated: bool,
        idempotency_key: str | None = None,
    ) -> None:
        """Send one JSON request and validate its common success envelope."""
        headers = {"accept": "application/json"}
        if authenticated:
            headers["x-external-user-id"] = _external_user_id()
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        payload = None
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["content-type"] = "application/json"
        request = Request(self.base_url + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise SyncError("mem-graph request failed") from error
        if not isinstance(envelope, dict) or envelope.get("code") != 0:
            raise SyncError("mem-graph returned an unsuccessful response")


def _source_reference(event: dict) -> str:
    """Encode local identity and revision as append-only provenance text."""
    return f"{event['memory_id']}#version={event['version']}#event={event['event']}"


def _idempotency_key(event: dict) -> str:
    """Return one stable retry key unique to the exact local event snapshot."""
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "topsailai-memory-sync-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_event(event: object) -> dict:
    """Validate the stable v1 create/update stdin contract."""
    if not isinstance(event, dict) or not REQUIRED_FIELDS.issubset(event):
        raise SyncError("invalid memory sync event")
    if event.get("schema_version") != 1 or event.get("event") not in SUPPORTED_EVENTS:
        raise SyncError("unsupported memory sync event")
    if not isinstance(event.get("version"), int) or isinstance(event["version"], bool) or event["version"] < 1:
        raise SyncError("invalid memory sync version")
    for field in REQUIRED_FIELDS - {"schema_version", "version"}:
        if not isinstance(event.get(field), str) or not event[field]:
            raise SyncError(f"invalid memory sync field: {field}")
    return event


def _positive_number(name: str, default: float) -> float:
    """Read one positive numeric setting with a safe default."""
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _enabled(name: str, default: bool) -> bool:
    """Read one boolean setting with a safe default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def check_port(
    base_url: str,
    timeout_seconds: float,
    *,
    connect: Callable = socket.create_connection,
) -> None:
    """Fail quickly unless the configured API host and port accept TCP connections."""
    endpoint = urlsplit(base_url)
    try:
        host = endpoint.hostname
        port = endpoint.port or {"http": 80, "https": 443}.get(endpoint.scheme)
    except ValueError as error:
        raise SyncError("invalid mem-graph API endpoint") from error
    if not host or not port:
        raise SyncError("invalid mem-graph API endpoint")
    try:
        connection = connect((host, port), timeout=timeout_seconds)
        connection.close()
    except OSError as error:
        raise SyncError(f"mem-graph port is unreachable: {host}:{port}") from error


def _retry(operation: Callable[[], None], sleep: Callable[[float], None]) -> None:
    """Retry a transient operation with capped exponential backoff."""
    attempts = int(_positive_number("TOPSAILAI_MEMORY_SYNC_RETRY_ATTEMPTS", DEFAULT_RETRY_ATTEMPTS))
    delay = _positive_number("TOPSAILAI_MEMORY_SYNC_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS)
    last_error = None
    for attempt in range(attempts):
        try:
            operation()
            return
        except SyncError as error:
            last_error = error
            if attempt + 1 < attempts:
                sleep(min(delay * (2**attempt), 2.0))
    raise last_error or SyncError("mem-graph operation failed")


def _record_sync(event: dict, *, synced: bool, error: str | None = None) -> None:
    """Persist sync observability after the bounded network operation exits."""
    try:
        memory_stat.record_memory_sync(
            event["workspace"], event["memory_id"], synced=synced, error=error
        )
    except Exception:
        logger.exception("failed to record memory sync state")


def process_event(
    event: dict,
    transport: MemGraphTransport,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Probe readiness and append one brand-new snapshot with retries."""
    try:
        _retry(transport.readiness, sleep)
        _retry(lambda: transport.create_snapshot(event), sleep)
    except SyncError as error:
        outbox.enqueue(event["workspace"], event)
        _record_sync(event, synced=False, error=str(error))
        logger.warning("queued memory sync event after mem-graph failure")
        return False
    _record_sync(event, synced=True)
    return True


def retry_outbox(
    workspace: str,
    transport: MemGraphTransport,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Retry pending snapshots once and retain only failed events."""
    pending = outbox.read(workspace)
    failed = []
    succeeded = 0
    for event in pending:
        try:
            _retry(transport.readiness, sleep)
            _retry(lambda current=event: transport.create_snapshot(current), sleep)
        except SyncError as error:
            failed.append(event)
            _record_sync(event, synced=False, error=str(error))
            continue
        _record_sync(event, synced=True)
        succeeded += 1
    outbox.replace(workspace, failed)
    return succeeded


def build_transport() -> MemGraphTransport:
    """Build the live transport from consumer boundary configuration."""
    base_url = os.environ.get("MEMGRAPH_API_BASE_URL", DEFAULT_BASE_URL)
    timeout = _positive_number("TOPSAILAI_MEMORY_SYNC_REQUEST_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
    return MemGraphTransport(base_url, timeout)


def main() -> int:
    """Consume one stdin event without propagating remote failures to core."""
    logging.basicConfig(level=logging.INFO)
    try:
        event = validate_event(json.load(sys.stdin))
    except (ValueError, SyncError):
        logger.warning("reject invalid memory sync stdin payload")
        return 2
    transport = build_transport()
    port_check_enabled = _enabled(
        "TOPSAILAI_MEMORY_SYNC_PORT_CHECK_ENABLED", DEFAULT_PORT_CHECK_ENABLED
    )
    port_check_timeout = _positive_number(
        "TOPSAILAI_MEMORY_SYNC_PORT_CHECK_TIMEOUT",
        DEFAULT_PORT_CHECK_TIMEOUT_SECONDS,
    )
    if port_check_enabled:
        try:
            check_port(transport.base_url, port_check_timeout)
        except SyncError as error:
            outbox.enqueue(event["workspace"], event)
            _record_sync(event, synced=False, error=str(error))
            logger.warning("queued memory sync event: %s", error)
            return 1
    retry_outbox(event["workspace"], transport)
    return 0 if process_event(event, transport) else 1


if __name__ == "__main__":
    raise SystemExit(main())
