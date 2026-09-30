"""Controlled worker entry points for supervisor protocol tests."""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time

from topsailai.hooks.worker_protocol import PROTOCOL_VERSION, decode_frame, encode_frame


def _arguments():
    """Parse the same controlled arguments as the production worker."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--result-fd", type=int, required=True)
    parser.add_argument("--request-limit", type=int, required=True)
    parser.add_argument("--response-limit", type=int, required=True)
    return parser.parse_args()


def _read_exact(size: int) -> bytes:
    """Read exact request bytes across pipe segmentation."""
    data = bytearray()
    while len(data) < size:
        chunk = os.read(0, size - len(data))
        if not chunk:
            raise RuntimeError("early request EOF")
        data.extend(chunk)
    return bytes(data)


def _request(args):
    """Read and decode the complete request frame."""
    header = _read_exact(4)
    size = struct.unpack("!I", header)[0]
    return decode_frame(header + _read_exact(size), args.request_limit)


def _response(request, **changes):
    """Build a correlated successful response with selected corruptions."""
    response = {
        "protocol_version": PROTOCOL_VERSION,
        "correlation_id": request["correlation_id"],
        "channel_token": request["channel_token"],
        "delivery_id": request["context"]["delivery_id"],
        "status": "success",
        "value": None,
        "error_category": None,
    }
    response.update(changes)
    return response


def wrong_correlation() -> int:
    """Write a valid response envelope carrying the wrong correlation ID."""
    args = _arguments()
    request = _request(args)
    os.write(args.result_fd, encode_frame(_response(request, correlation_id="wrong"), args.response_limit))
    return 0


def wrong_channel() -> int:
    """Write a valid response envelope carrying the wrong channel token."""
    args = _arguments()
    request = _request(args)
    os.write(args.result_fd, encode_frame(_response(request, channel_token="wrong"), args.response_limit))
    return 0


def wrong_delivery() -> int:
    """Write a valid response envelope carrying the wrong delivery ID."""
    args = _arguments()
    request = _request(args)
    os.write(args.result_fd, encode_frame(_response(request, delivery_id="wrong"), args.response_limit))
    return 0


def malformed() -> int:
    """Write bytes that cannot form a valid protocol frame."""
    args = _arguments()
    _request(args)
    os.write(args.result_fd, b"bad")
    return 0


def no_read() -> int:
    """Keep stdin unread so the host request pipe can fill."""
    _arguments()
    time.sleep(60)
    return 0


def startup_flood() -> int:
    """Flood diagnostics before consuming a potentially large request."""
    args = _arguments()
    chunk = b"f" * 65_536
    for _ in range(16):
        os.write(sys.stdout.fileno(), chunk)
        os.write(sys.stderr.fileno(), chunk)
    request = _request(args)
    os.write(args.result_fd, encode_frame(_response(request), args.response_limit))
    return 0


def late_result() -> int:
    """Return a valid result only after the caller deadline."""
    args = _arguments()
    request = _request(args)
    time.sleep(0.2)
    os.write(args.result_fd, encode_frame(_response(request), args.response_limit))
    return 0
