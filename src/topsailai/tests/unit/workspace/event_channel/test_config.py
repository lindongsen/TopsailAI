"""Unit tests for the event channel configuration defaults.

The channel is enabled by default so an operator gets observability without
opting in. That default is only safe because the channel is hardened against
blocking and against abnormal exits, so these tests pin both the default and the
explicit opt-out.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Verify the event channel is enabled by default and can be disabled
"""

from __future__ import annotations

import pytest

from topsailai.workspace.event_channel.config import (
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_HEARTBEAT_TIMEOUT,
    DEFAULT_MAX_FRAME_BYTES,
    DEFAULT_MAX_SUBSCRIBERS,
    DEFAULT_QUEUE_SIZE,
    EventChannelConfig,
    get_event_channel_config,
)


def test_dataclass_default_is_enabled():
    """A bare configuration must enable the channel."""
    assert EventChannelConfig().enabled is True


def test_from_env_defaults_to_enabled_when_the_variable_is_unset(monkeypatch):
    """An unset switch must leave the channel enabled."""
    monkeypatch.delenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", raising=False)

    assert EventChannelConfig.from_env().enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "disabled"])
def test_from_env_honours_an_explicit_opt_out(monkeypatch, value):
    """Every documented false spelling must disable the channel."""
    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", value)

    assert EventChannelConfig.from_env().enabled is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "enabled"])
def test_from_env_honours_an_explicit_opt_in(monkeypatch, value):
    """Every documented true spelling must enable the channel."""
    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", value)

    assert EventChannelConfig.from_env().enabled is True


def test_from_env_keeps_the_documented_numeric_defaults(monkeypatch):
    """Enabling by default must not change any other default."""
    monkeypatch.delenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", raising=False)

    config = EventChannelConfig.from_env()

    assert config.max_subscribers == DEFAULT_MAX_SUBSCRIBERS
    assert config.queue_size == DEFAULT_QUEUE_SIZE
    assert config.heartbeat_interval == DEFAULT_HEARTBEAT_INTERVAL
    assert config.heartbeat_timeout == DEFAULT_HEARTBEAT_TIMEOUT
    assert config.max_frame_bytes == DEFAULT_MAX_FRAME_BYTES


def test_get_event_channel_config_reads_the_environment(monkeypatch):
    """The accessor must reflect the environment on every call."""
    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", "0")
    assert get_event_channel_config().enabled is False

    monkeypatch.setenv("TOPSAILAI_EVENT_CHANNEL_ENABLED", "1")
    assert get_event_channel_config().enabled is True
