'''
Author: DawsonLin
Purpose: Define per-run interaction policy for LLM chat request retries.
'''

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class LLMRetryInteractionPolicy:
    """Describe which user choices are available for an LLM chat request.

    This policy controls retries of one LLM chat request with the same messages.
    It does not authorize restarting or retrying the Agent loop.
    """

    interactive_enabled: bool = False
    allow_back_to_chat: bool = False
    input_func: Optional[Callable[[str], str]] = None
    max_manual_retry_cycles: int = 7
    max_invalid_choices: int = 3

    def __post_init__(self) -> None:
        """Validate bounded retry-policy limits."""
        if (
                isinstance(self.max_manual_retry_cycles, bool)
                or not isinstance(self.max_manual_retry_cycles, int)
                or self.max_manual_retry_cycles < 0
            ):
            raise ValueError("max_manual_retry_cycles must be a non-negative integer")
        if (
                isinstance(self.max_invalid_choices, bool)
                or not isinstance(self.max_invalid_choices, int)
                or self.max_invalid_choices < 1
            ):
            raise ValueError("max_invalid_choices must be a positive integer")

    def can_prompt(self) -> bool:
        """Return whether this run explicitly permits an input prompt."""
        return self.interactive_enabled and self.input_func is not None


def read_retry_exhaustion_action(policy, *, allow_retry, warning_func):
    """Read one bounded retry-exhaustion action from the interactive user.

    The warning output is injected via ``warning_func`` so this provider-neutral
    helper never depends on the OpenAI-coupled ``llm_base`` module.
    """
    action_lines = []
    if allow_retry:
        action_lines.append("1. Retry the same LLM request")
    back_number = None
    if policy.allow_back_to_chat:
        back_number = len(action_lines) + 1
        action_lines.append(f"{back_number}. Back to chat")
    exit_number = len(action_lines) + 1
    action_lines.append(f"{exit_number}. Exit")
    prompt = (
        "LLM retry attempts exhausted.\n"
        + "\n".join(action_lines)
        + f"\nSelect [1-{exit_number}]: "
    )

    for _ in range(policy.max_invalid_choices):
        try:
            choice = str(policy.input_func(prompt)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "exit"
        if allow_retry and choice in {"1", "retry"}:
            return "retry"
        if policy.allow_back_to_chat and choice in {str(back_number), "back"}:
            return "back"
        if choice in {str(exit_number), "exit", "abort"}:
            return "exit"
        warning_func("Please select a valid LLM retry action.")
    return "exit"
