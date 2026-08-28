"""Gherkin scenarios guarding the string-only tools against badly typed arguments."""

from pytest_bdd import scenarios


scenarios("features/tools_param_coercion_str_only_guard.feature")
