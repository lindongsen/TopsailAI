"""Typed models for the JEV decision tool."""

from dataclasses import dataclass


@dataclass(frozen=True)
class JevConfig:
    """Hold validated JEV transport and context configuration."""

    endpoint: str
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int
    max_context_messages: int
    max_context_chars: int
