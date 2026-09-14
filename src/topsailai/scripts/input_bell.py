#!/usr/bin/env python3
"""Periodically check `topsailai workspace` for INPUT sessions and ring a bell."""

import argparse
import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
_ALSA_PCM_FILE = Path("/proc/asound/pcm")
_PROC_DIR = Path("/proc")
_AUTO_SOUND_COMMAND: Optional[
    Tuple[str, Optional[Dict[str, str]], Optional[str]]
] = None


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


def _pulseaudio_sessions(
    proc_dir: Path = _PROC_DIR,
) -> List[Tuple[str, str, str]]:
    """Return active PulseAudio server addresses with their account details."""
    try:
        import pwd

        unix_socket_lines = (proc_dir / "net" / "unix").read_text(
            encoding="utf-8"
        ).splitlines()
    except (ImportError, OSError):
        return []
    socket_paths = {}
    for line in unix_socket_lines[1:]:
        fields = line.split()
        if len(fields) >= 8 and fields[7].endswith("/native"):
            socket_paths[fields[6]] = fields[7]

    sessions = []
    try:
        process_dirs = list(proc_dir.iterdir())
    except OSError:
        return []
    for process_dir in process_dirs:
        if not process_dir.name.isdigit():
            continue
        try:
            if (process_dir / "comm").read_text(encoding="utf-8").strip() != "pulseaudio":
                continue
            status_lines = (process_dir / "status").read_text(encoding="utf-8").splitlines()
            uid_line = next(line for line in status_lines if line.startswith("Uid:"))
            account = pwd.getpwuid(int(uid_line.split()[1]))
            descriptors = list((process_dir / "fd").iterdir())
        except (OSError, KeyError, StopIteration, ValueError):
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(str(descriptor))
            except OSError:
                continue
            if not target.startswith("socket:[") or not target.endswith("]"):
                continue
            socket_path = socket_paths.get(target[8:-1])
            if not socket_path:
                continue
            session = ("unix:" + socket_path, account.pw_name, account.pw_dir)
            if session not in sessions:
                sessions.append(session)
    return sessions


def _alsa_playback_devices(pcm_file: Path = _ALSA_PCM_FILE) -> List[str]:
    """Return unique direct ALSA playback devices advertised by the kernel."""
    try:
        lines = pcm_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    devices = []
    for line in lines:
        identifier, _, details = line.partition(":")
        if "playback" not in details:
            continue
        card, separator, device = identifier.partition("-")
        if not separator or not card.isdigit() or not device.isdigit():
            continue
        candidate = "plughw:{},{}".format(int(card), int(device))
        if candidate not in devices:
            devices.append(candidate)
    return devices


def _sound_candidates(
) -> List[Tuple[str, Optional[Dict[str, str]], Optional[str]]]:
    """Build unique ffplay candidates from PulseAudio through direct ALSA."""
    candidates = []
    for server, username, home in _pulseaudio_sessions():
        candidates.append(
            (
                DEFAULT_SOUND_CMD,
                {
                    "HOME": home,
                    "PULSE_SERVER": server,
                    "SDL_AUDIODRIVER": "pulseaudio",
                },
                username,
            )
        )
    candidates.append((DEFAULT_SOUND_CMD, None, None))
    for device in _alsa_playback_devices():
        candidate = (
            DEFAULT_SOUND_CMD,
            {"SDL_AUDIODRIVER": "alsa", "AUDIODEV": device},
            None,
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _run_sound_command(
    sound_cmd: str,
    extra_env: Optional[Dict[str, str]],
    run_as_user: Optional[str] = None,
) -> bool:
    """Run one ffplay command and reject reported audio-initialization failures."""
    command = shlex.split(sound_cmd)
    if run_as_user:
        try:
            import pwd

            target_uid = pwd.getpwnam(run_as_user).pw_uid
        except (ImportError, KeyError):
            return False
        if not hasattr(os, "geteuid"):
            return False
        effective_uid = os.geteuid()
        if effective_uid != target_uid:
            if effective_uid != 0:
                return False
            command = ["runuser", "-u", run_as_user, "--"] + command
    environment = None if extra_env is None else dict(os.environ, **extra_env)
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("failed to play bell sound: %s", error)
        return False
    stderr = result.stderr.lower()
    failed_markers = (
        "couldn't open audio device",
        "audio open failed",
        "failed to open file",
    )
    if result.returncode != 0 or any(marker in stderr for marker in failed_markers):
        logger.warning("bell sound command failed: %s", stderr.strip() or result.returncode)
        return False
    return True


def _ring_bell(sound_cmd: Optional[str]) -> bool:
    """Play an explicit command or detect and cache an ffplay output route."""
    global _AUTO_SOUND_COMMAND
    if sound_cmd:
        return _run_sound_command(sound_cmd, None)
    if _AUTO_SOUND_COMMAND:
        return _run_sound_command(*_AUTO_SOUND_COMMAND)
    for candidate in _sound_candidates():
        if _run_sound_command(*candidate):
            _AUTO_SOUND_COMMAND = candidate
            logger.info("selected ffplay bell audio output")
            return True
    logger.warning("no usable ffplay audio output was found")
    return False


def _run_once(
    topsailai_cmd: str, sound_cmd: Optional[str]
) -> Tuple[bool, bool]:
    """Check once and return whether INPUT was found and the bell played."""
    found = _has_input_sessions(topsailai_cmd)
    if not found:
        return False, False
    return True, _ring_bell(sound_cmd)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the input bell script."""
    parser = argparse.ArgumentParser(
        prog="input_bell.py",
        description="Periodically check `topsailai workspace` for INPUT sessions and ring a bell.",
    )
    parser.add_argument(
        "--test-sound",
        action="store_true",
        help="Play the bell sound once and exit to verify audio output.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Run the periodic INPUT check loop or a one-shot sound test."""
    args = _parse_args(argv)
    sound_cmd = os.environ.get(SOUND_CMD_ENV, "").strip() or None
    if args.test_sound:
        if _ring_bell(sound_cmd):
            logger.info("sound test passed: bell played")
            return 0
        logger.warning("sound test failed: no usable audio output")
        return 1

    interval = _env_int(INTERVAL_SEC_ENV, DEFAULT_INTERVAL_SEC)
    once = _env_bool(ONCE_ENV, False)
    topsailai_cmd = os.environ.get(TOPSAILAI_CMD_ENV, "").strip() or DEFAULT_TOPSAILAI_CMD

    logger.info(
        "input bell started: interval=%ss once=%s topsailai_cmd=%s",
        interval,
        once,
        topsailai_cmd,
    )

    while True:
        try:
            found, played = _run_once(topsailai_cmd, sound_cmd)
            if played:
                logger.info("detected INPUT session(s), bell played")
            elif found:
                logger.warning("detected INPUT session(s), but bell playback failed")
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
