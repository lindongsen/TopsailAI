"""Single source of truth for the launcher argv used by every launch path.

Foreground launches and the detached supervisor both spawn the same launcher,
so the argv must be built in one place; otherwise a flag added to one path is
silently missing from the other.
"""

from __future__ import annotations

from typing import Optional

_LAUNCHER = "topsailai_launch_agent"


def launcher_command(session_id: str, *, driver: Optional[str] = None,
                     non_interactive: bool = False,
                     task: Optional[str] = None) -> list[str]:
    """Build the launcher argv for one fresh launch or resume.

    A resume driver is a different executable, so it never receives launcher
    flags. ``--non-interactive`` suppresses launcher prompts only; the agent's
    own interactive mode stays controlled by ``TOPSAILAI_INTERACTIVE_MODE`` and
    is deliberately not touched here. ``task`` supplies the fresh launcher's
    first user task without exposing it through the process environment.
    """
    if driver:
        return [driver]
    command = [_LAUNCHER, "--subprocess", "--session-id", session_id]
    if non_interactive:
        command.append("--non-interactive")
    if task is not None:
        command.extend(["--task", task])
    return command
