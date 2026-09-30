"""Importable real-process handlers for isolated hook worker tests."""

from __future__ import annotations

import asyncio
import os
import sys
import time


def sync_success(context):
    """Return selected detached context fields synchronously."""
    return {"delivery": context.delivery_id, "payload": dict(context.event.payload)}


async def async_success(context):
    """Return selected detached context fields asynchronously."""
    await asyncio.sleep(0)
    return {"binding": context.binding_id}


class _CustomAwaitable:
    """Provide a non-coroutine awaitable for protocol compatibility testing."""

    def __await__(self):
        async def complete():
            return {"awaitable": True}

        return complete().__await__()


def custom_awaitable_success(context):
    """Return an awaitable object that is not itself a coroutine object."""
    return _CustomAwaitable()


def raise_exception(context):
    """Raise a plugin exception that must stay inside the worker."""
    raise RuntimeError("sensitive plugin detail")


def return_invalid_value(context):
    """Return a non-JSON value that the worker must classify as invalid output."""
    return object()


def block_forever(context):
    """Block until the supervisor terminates the owned worker."""
    while True:
        time.sleep(1)


def flood_output(context):
    """Flood both inherited diagnostic streams before returning."""
    chunk = b"x" * 65_536
    for _ in range(32):
        os.write(sys.stdout.fileno(), chunk)
        os.write(sys.stderr.fileno(), chunk)
    return {"done": True}


def spawn_descendant_and_block(context):
    """Spawn an in-group descendant and expose its PID before blocking."""
    import subprocess

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.write(sys.stdout.fileno(), f"CHILD:{child.pid}\n".encode())
    while True:
        time.sleep(1)


async def block_coroutine(context):
    """Await forever until the worker is terminated."""
    await asyncio.Event().wait()


def raise_system_exit(context):
    """Raise worker-origin process control flow."""
    raise SystemExit(9)


def raise_keyboard_interrupt(context):
    """Raise worker-origin keyboard control flow."""
    raise KeyboardInterrupt()


def raise_cancelled(context):
    """Raise worker-origin coroutine cancellation."""
    raise asyncio.CancelledError()
