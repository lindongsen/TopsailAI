"""Environment configuration for the JEV decision tool."""

import math
import os
from urllib.parse import urlsplit, urlunsplit

from topsailai.tools.jev_tool_utils.models import JevConfig


class JevConfigError(ValueError):
    """Identify invalid JEV configuration without exposing secret values."""

    def __init__(self, reason: str):
        """Initialize the configuration error with a stable reason."""
        super().__init__(reason)
        self.reason = reason


def _positive_int(name: str, default: str) -> int:
    """Read a positive integer environment value."""
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError) as exc:
        raise JevConfigError(f"invalid_{name.lower()}") from exc
    if value <= 0:
        raise JevConfigError(f"invalid_{name.lower()}")
    return value


def _non_negative_int(name: str, default: str) -> int:
    """Read a non-negative integer environment value."""
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError) as exc:
        raise JevConfigError(f"invalid_{name.lower()}") from exc
    if value < 0:
        raise JevConfigError(f"invalid_{name.lower()}")
    return value


def _timeout() -> float:
    """Read a positive finite timeout in seconds."""
    try:
        value = float(os.getenv("TOPSAILAI_JEV_TIMEOUT_SECONDS", "10"))
    except (TypeError, ValueError) as exc:
        raise JevConfigError("invalid_topsailai_jev_timeout_seconds") from exc
    if not math.isfinite(value) or value <= 0:
        raise JevConfigError("invalid_topsailai_jev_timeout_seconds")
    return value


def _endpoint(base_url: str) -> str:
    """Validate an HTTP(S) origin and append the fixed API route."""
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise JevConfigError("invalid_topsailai_jev_base_url") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise JevConfigError("invalid_topsailai_jev_base_url")
    if parsed.username is not None or parsed.password is not None:
        raise JevConfigError("invalid_topsailai_jev_base_url")
    if parsed.query or parsed.fragment:
        raise JevConfigError("invalid_topsailai_jev_base_url")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/systemone"):
        endpoint_path = path
    else:
        endpoint_path = f"{path}/v1/systemone" if path else "/v1/systemone"
    return urlunsplit((parsed.scheme, netloc, endpoint_path, "", ""))


def load_config() -> JevConfig:
    """Load and validate JEV configuration from environment variables."""
    base_url = os.getenv("TOPSAILAI_JEV_BASE_URL", "").strip()
    api_key = os.getenv("TOPSAILAI_JEV_API_KEY", "").strip()
    model = os.getenv("TOPSAILAI_JEV_MODEL", "jev-latest").strip()
    if not base_url:
        raise JevConfigError("missing_topsailai_jev_base_url")
    if not api_key:
        raise JevConfigError("missing_topsailai_jev_api_key")
    if not model:
        raise JevConfigError("invalid_topsailai_jev_model")
    return JevConfig(
        endpoint=_endpoint(base_url),
        api_key=api_key,
        model=model,
        timeout_seconds=_timeout(),
        max_retries=_non_negative_int("TOPSAILAI_JEV_MAX_RETRIES", "1"),
        max_context_messages=_positive_int(
            "TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES", "50"
        ),
        max_context_chars=_positive_int(
            "TOPSAILAI_JEV_MAX_CONTEXT_CHARS", "60000"
        ),
    )
