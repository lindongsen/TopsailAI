"""Run operator-configured scripts before one complete-message input.

Author: DawsonLin

This Module mirrors ``TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER``: the operator
lists scripts in one environment variable and each script runs as an isolated
child process with the same parser, timeout and ``env_keys`` options.

The checkpoint fires once per complete message, so an unset variable must cost
almost nothing. ``hook_tool.call_hook_scripts`` returns immediately when the
variable is absent, and no child process is created in that case.

A script failure is logged and never interrupts input: the operator's script is
an observation, not a gate on the human's ability to type.

The prompt text travels to the child as ``TOPSAILAI_INPUT_TIPS`` because a
Script child receives no payload and its stdin is closed; the environment is the
only channel, exactly as ``TOPSAILAI_FINAL_ANSWER`` works for the post-answer
scripts.
"""

from topsailai.logger.log_chat import logger
from topsailai.utils import hook_tool

ENV_KEY = "TOPSAILAI_HOOK_SCRIPTS_BEFORE_INPUT_MESSAGE"
TIPS_ENV = "TOPSAILAI_INPUT_TIPS"


def main(**payload):
    """Run the configured scripts; a failure is logged and never raised."""
    tips = payload.get("tips") or ""
    try:
        results = hook_tool.call_hook_scripts(ENV_KEY, env_info={TIPS_ENV: tips})
    except Exception:
        logger.warning("before_input_message_hook_scripts_failed", exc_info=True)
        return {"scripts": 0}
    return {"scripts": len(results)}


__all__ = ["main", "ENV_KEY", "TIPS_ENV"]
