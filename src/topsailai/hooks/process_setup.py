"""Identity-safe ownership for result-pipe descriptors during process setup."""

from __future__ import annotations

import os
import threading

from topsailai.hooks.process_state import ChannelCloseState, LaunchRecord


class ProcessSetupMixin:
    """Track result-pipe ownership before process resources are published."""

    def _adopt_setup_pipe(
        self, record: LaunchRecord, result_read: int, result_write: int
    ) -> None:
        """Record both pipe ends before probing their stable identities."""
        descriptors = (
            ("result_read", result_read),
            ("result_write", result_write),
        )
        with record.condition:
            for name, descriptor in descriptors:
                channel = record.cleanup.setup_channels[name]
                channel.state = "uncertain"
                channel.descriptor = descriptor
                channel.identity = None
                channel.resource = descriptor
                channel.close_owner = None
                channel.close_started = False
                channel.identity_pending = True

        identity_unavailable = False
        for name, descriptor in descriptors:
            status, identity = self._descriptor_identity(descriptor)
            with record.condition:
                channel = record.cleanup.setup_channels[name]
                if status == "open" and identity is not None:
                    channel.state = "open"
                    channel.identity = identity
                    channel.identity_pending = False
                elif status == "closed":
                    self._settle_setup_channel(channel)
                else:
                    identity_unavailable = True
        if identity_unavailable:
            raise OSError("result pipe descriptor identity is unavailable")

    def _close_setup_channel(self, record: LaunchRecord, name: str) -> None:
        """Close one setup descriptor without losing uncertain ownership."""
        channel = record.cleanup.setup_channels[name]
        descriptor: int | None = None
        try:
            with record.condition:
                if channel.state == "closed":
                    return
                descriptor = channel.resource if type(channel.resource) is int else None
                if descriptor is None:
                    channel.state = "uncertain"
                    return
                if channel.identity_pending:
                    status, _ = self._descriptor_identity(descriptor)
                    if status == "closed":
                        self._settle_setup_channel(channel)
                        return
                    # A later observation cannot prove that an identity-unknown
                    # descriptor still denotes the pipe created by this record.
                    channel.state = "uncertain"
                    return
                else:
                    state = self._classify_interrupted_close(channel, descriptor)
                    if state == "closed":
                        self._settle_setup_channel(channel)
                        return
                    if state != "open":
                        channel.state = state
                        return
                channel.close_owner = None
                channel.close_started = False
                self._prepare_channel_close(channel, descriptor, threading.get_ident())
            self._before_channel_close(record, name, descriptor)
            with record.condition:
                channel.close_started = True
            os.close(descriptor)
            self._after_setup_close_before_commit(record, name, descriptor)
            with record.condition:
                self._settle_setup_channel(channel)
        except BaseException as exc:
            if descriptor is not None:
                state = self._classify_interrupted_close(channel, descriptor)
                with record.condition:
                    channel.state = state
                    channel.close_owner = None
                    channel.close_started = False
                    if state == "closed":
                        self._settle_setup_channel(channel)
            if not isinstance(exc, Exception):
                raise
            return
        self._after_channel_close(record, name, descriptor)

    def _transfer_setup_result_read(self, record: LaunchRecord) -> None:
        """Atomically move the read descriptor into the published result channel."""
        setup = record.cleanup.setup_channels["result_read"]
        descriptor = setup.resource if type(setup.resource) is int else None
        if setup.state != "open" or descriptor is None or setup.identity_pending:
            raise RuntimeError("result read descriptor is not owned")
        status, identity = self._descriptor_identity(descriptor)
        if status != "open" or identity != setup.identity:
            raise RuntimeError("result read descriptor identity changed")
        result = record.cleanup.channels["result"]
        result.state = "open"
        result.descriptor = descriptor
        result.identity = identity
        result.resource = descriptor
        result.close_owner = None
        result.close_started = False
        record.result_fd = descriptor
        self._settle_setup_channel(setup)

    @staticmethod
    def _settle_setup_channel(channel: ChannelCloseState) -> None:
        """Release one confirmed-closed or transferred setup obligation."""
        channel.state = "closed"
        channel.descriptor = None
        channel.identity = None
        channel.resource = None
        channel.close_owner = None
        channel.close_started = False
        channel.identity_pending = False

    def _after_setup_close_before_commit(
        self, record: LaunchRecord, name: str, descriptor: int
    ) -> None:
        """Provide a deterministic seam after setup close and before state commit."""
