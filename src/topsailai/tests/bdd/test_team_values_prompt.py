"""Gherkin bindings for Team-level shared values prompts.

Author: DawsonLin
"""

from pytest_bdd import scenarios

from tests.bdd.steps.team_values_prompt_steps import *  # noqa: F403


scenarios("features/team_values_prompt.feature")
