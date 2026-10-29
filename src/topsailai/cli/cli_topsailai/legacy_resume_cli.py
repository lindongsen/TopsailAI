"""Shared parsing for legacy interactive and project resume commands."""

from __future__ import annotations

import argparse
import shlex
from typing import Optional, Sequence


RESUME_DRIVER_OPTIONS = (
    "topsailai_agent_chats",
    "topsailai_agent_plan_tasks",
    "ai-team-flow-dev",
)


class UniqueResumeDriver(argparse.Action):
    """Reject conflicting repeated drivers while accepting identical repeats."""

    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None)
        if current is not None and current != values:
            raise argparse.ArgumentError(self, f"conflicting {option_string} values")
        setattr(namespace, self.dest, values)


def add_driver_argument(parser: argparse.ArgumentParser) -> None:
    """Add the strict shared resume-driver option to *parser*."""
    parser.add_argument(
        "-d",
        "--driver",
        choices=RESUME_DRIVER_OPTIONS,
        default=None,
        action=UniqueResumeDriver,
        help="resume driver (default: topsailai_agent_chats)",
    )


def build_parser(*, target_name: str) -> argparse.ArgumentParser:
    """Build a strict parser for a legacy resume target and driver."""
    parser = argparse.ArgumentParser(
        prog="resume",
        allow_abbrev=False,
        add_help=False,
    )
    parser.add_argument(target_name)
    add_driver_argument(parser)
    return parser


def parse_args(tokens: Sequence[str], *, target_name: str):
    """Parse resume tokens, returning ``None`` after argparse reports errors."""
    try:
        return build_parser(target_name=target_name).parse_args(list(tokens))
    except SystemExit:
        return None


def parse_text(text: str, *, target_name: str):
    """Shell-tokenize and parse an interactive resume argument string."""
    try:
        tokens = shlex.split(text)
    except ValueError as error:
        parser = build_parser(target_name=target_name)
        try:
            parser.error(str(error))
        except SystemExit:
            return None
    return parse_args(tokens, target_name=target_name)
