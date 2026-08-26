"""Shared fixtures for CLI behavior tests."""


def pytest_configure(config):
    """Register markers used by the initial BDD feature set."""
    config.addinivalue_line("markers", "bdd: Gherkin behavior test")
    config.addinivalue_line(
        "markers", "noninteractive: non-interactive CLI behavior"
    )
pytest_plugins = [
    "tests.bdd.steps.project_steps",
    "tests.bdd.steps.models_steps",
    "tests.bdd.steps.docs_steps",
    "tests.bdd.steps.cached_tokens_steps",
    "tests.bdd.steps.tokenstat_steps",
    "tests.bdd.steps.session_context_steps",
    "tests.bdd.steps.summarize_watermark_steps",
    "tests.bdd.steps.summarize_head_retention_steps",
    "tests.bdd.steps.summarize_threshold_steps",
    "tests.bdd.steps.hard_interrupt_steps",
    "tests.bdd.steps.hard_interrupt_mock_server_steps",
]
