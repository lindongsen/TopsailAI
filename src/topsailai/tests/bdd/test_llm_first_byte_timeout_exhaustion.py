"""BDD entry point for U5 retry-exhaustion acceptance."""

import pytest
from pytest_bdd import scenarios

from tests.bdd.steps.test_llm_first_byte_timeout_exhaustion_steps import *  # noqa: F403


pytestmark = pytest.mark.slow

scenarios("features/llm_first_byte_timeout_exhaustion.feature")
