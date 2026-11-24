"""Single source of truth for the launcher argv used by every launch path.

Foreground launches and the detached supervisor both spawn the same launcher,
so the argv must be built in one place; otherwise a flag added to one path is
silently missing from the other.
"""

from __future__ import annotations

from typing import Mapping, Optional

_LAUNCHER = "topsailai_launch_agent"


def launcher_command(session_id: str, *, driver: Optional[str] = None,
                     non_interactive: bool = False,
                     task: Optional[str] = None,
                     launcher_driver: Optional[str] = None,
                     env_overrides: Optional[Mapping[str, str]] = None) -> list[str]:
    """Build the launcher argv for one fresh launch or resume.

    A resume driver is a different executable, so it never receives launcher
    flags. ``--non-interactive`` suppresses launcher prompts only; the agent's
    own interactive mode stays controlled by ``TOPSAILAI_INTERACTIVE_MODE`` and
    is deliberately not touched here. ``task`` supplies the fresh launcher's
    first user task without exposing it through the process environment.

    ``launcher_driver`` is the opposite case: it selects which driver the
    launcher itself should run, so it is forwarded as the launcher's own
    ``--driver`` flag. The launcher still resolves settings.yaml, merges the
    configured environment and injects context, which is exactly what a fresh
    launch needs; passing it as ``driver`` would replace the whole argv instead.

    ``env_overrides`` are forwarded as repeated ``--env KEY=VALUE`` flags rather
    than through this process's environment, because the launcher merges
    settings.yaml over its inherited environment. Only the launcher's own flag
    can outrank a configured value, so a caller-supplied value must travel as
    argv. Names are emitted in sorted order so the argv is reproducible.
    """
    if driver:
        return [driver]
    command = [_LAUNCHER, "--subprocess", "--session-id", session_id]
    if non_interactive:
        command.append("--non-interactive")
    if launcher_driver is not None:
        command.extend(["--driver", launcher_driver])
    if task is not None:
        command.extend(["--task", task])
    for name in sorted(env_overrides or {}):
        command.extend(["--env", f"{name}={env_overrides[name]}"])
    return command
