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
