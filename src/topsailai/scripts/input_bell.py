#!/usr/bin/env python3
"""Periodically check `topsailai workspace` for INPUT sessions and ring a bell."""

import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_ENV_FILE = SCRIPT_DIR / (Path(__file__).stem + ".env")

# Script-owned environment variables.
INTERVAL_SEC_ENV = "TOPSAILAI_INPUT_BELL_INTERVAL_SEC"
ONCE_ENV = "TOPSAILAI_INPUT_BELL_ONCE"
SOUND_CMD_ENV = "TOPSAILAI_INPUT_BELL_SOUND"
TOPSAILAI_CMD_ENV = "TOPSAILAI_INPUT_BELL_TOPSAILAI_CMD"

DEFAULT_INTERVAL_SEC = 30
DEFAULT_TOPSAILAI_CMD = "topsailai"
# ffplay generates a short sine tone without needing a display or audio files.
DEFAULT_SOUND_CMD = (
    "ffplay -nodisp -autoexit -loglevel quiet "
    "-f lavfi -i sine=frequency=880:duration=0.3"
)


def _load_script_env(env_file: Path = SCRIPT_ENV_FILE) -> None:
    """Load the script-specific dotenv file without overriding process values."""
    if not env_file.is_file():
        return
    try:
        load_dotenv(env_file, override=False)
    except Exception as error:
        logger.warning("failed to load script environment file %s: %s", env_file, error)


_load_script_env()


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment value, falling back to the default."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Parse a positive integer environment value, falling back to the default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid integer for %s: %r, using default %s", name, raw, default)
        return default
    return value if value > 0 else default


def _has_input_sessions(topsailai_cmd: str) -> bool:
    """Return True when `topsailai workspace` lists at least one INPUT session."""
    try:
        result = subprocess.run(
            [topsailai_cmd, "workspace"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("failed to run %s workspace: %s", topsailai_cmd, error)
        return False
    if result.returncode != 0:
        logger.warning("%s workspace exited with code %s", topsailai_cmd, result.returncode)
        return False
    return any(line.strip() for line in result.stdout.splitlines() if "INPUT" in line)


def _ring_bell(sound_cmd: str) -> None:
    """Play the configured bell sound, ignoring playback failures."""
    try:
        subprocess.run(
            shlex.split(sound_cmd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("failed to play bell sound: %s", error)


def _run_once(topsailai_cmd: str, sound_cmd: str) -> bool:
    """Check once and ring the bell when INPUT sessions exist; return found."""
    found = _has_input_sessions(topsailai_cmd)
    if found:
        _ring_bell(sound_cmd)
    return found


def main() -> int:
    """Run the periodic INPUT check loop."""
    interval = _env_int(INTERVAL_SEC_ENV, DEFAULT_INTERVAL_SEC)
    once = _env_bool(ONCE_ENV, False)
    topsailai_cmd = os.environ.get(TOPSAILAI_CMD_ENV, "").strip() or DEFAULT_TOPSAILAI_CMD
    sound_cmd = os.environ.get(SOUND_CMD_ENV, "").strip() or DEFAULT_SOUND_CMD

    logger.info(
        "input bell started: interval=%ss once=%s topsailai_cmd=%s",
        interval,
        once,
        topsailai_cmd,
    )

    while True:
        try:
            found = _run_once(topsailai_cmd, sound_cmd)
            if found:
                logger.info("detected INPUT session(s), bell played")
        except KeyboardInterrupt:
            logger.info("input bell stopped by interrupt")
            return 0
        if once:
            return 0 if found else 1
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
