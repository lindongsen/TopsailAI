"""U11D real Catalog wrapper acceptance. Author: DawsonLin."""
from pytest_bdd import scenarios

from tests.bdd.steps.configured_hook_readiness_steps import *  # noqa: F403

scenarios("features/configured_hook_readiness.feature")
