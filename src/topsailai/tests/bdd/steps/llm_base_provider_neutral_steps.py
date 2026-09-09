"""Unique BDD steps for provider-neutral LLM base import."""

import subprocess
import sys

from pytest_bdd import given, then, when

# Probe script run in a clean subprocess so the shared test-process
# ``sys.modules`` cannot mask whether importing ``llm_base`` loads openai.
_PROBE_IMPORT = """
import sys
from ai_base import llm_base
assert "openai" not in sys.modules, "openai should not be imported by llm_base"
assert "httpx" not in sys.modules, "httpx should not be imported by llm_base"
assert "httpcore" not in sys.modules, "httpcore should not be imported by llm_base"
print("IMPORT_OK")
"""

_PROBE_INSTANTIATE = """
import sys
from ai_base import llm_base
assert "openai" not in sys.modules, "openai should not be imported by llm_base"
from ai_base.llm_base import LLMModel
m = LLMModel()
assert m.provider == "openai", m.provider
assert m.provider_backend.name == "openai", m.provider_backend.name
assert "openai" in sys.modules, "openai should be loaded on demand"
print("INSTANTIATE_OK")
"""


@given("a clean Python subprocess")
def given_clean_python_subprocess():
    """No-op: each scenario runs its probe in an isolated subprocess."""
    return True


@when("the subprocess imports ai_base.llm_base")
def when_subprocess_imports_llm_base():
    """Run the import-only probe in a clean subprocess."""
    _run_probe(_PROBE_IMPORT)


@when("the subprocess imports ai_base.llm_base and instantiates LLMModel")
def when_subprocess_imports_and_instantiates():
    """Run the instantiate probe in a clean subprocess."""
    _run_probe(_PROBE_INSTANTIATE)


@then("the OpenAI SDK is not loaded")
def then_openai_not_loaded():
    """The import-only probe already asserted openai is absent."""
    return True


@then("the httpx transport is not loaded")
def then_httpx_not_loaded():
    """The import-only probe already asserted httpx is absent."""
    return True


@then("the httpcore transport is not loaded")
def then_httpcore_not_loaded():
    """The import-only probe already asserted httpcore is absent."""
    return True


@then("the OpenAI backend resolves to the openai provider")
def then_openai_backend_resolves():
    """The instantiate probe already asserted provider and backend names."""
    return True


@then("the OpenAI SDK is loaded only after instantiation")
def then_openai_loaded_after_instantiation():
    """The instantiate probe already asserted on-demand loading."""
    return True


def _run_probe(script: str) -> None:
    """Run a probe script in a clean subprocess and assert it succeeds."""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd="/TopsailAI/src/topsailai",
    )
    assert result.returncode == 0, (
        f"probe failed (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
