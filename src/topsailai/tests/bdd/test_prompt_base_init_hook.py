"""PromptBase initialization Hook Point BDD scenarios. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.prompt_base_init_hook_steps import *  # noqa: F403

scenarios("features/prompt_base_init_hook.feature")
