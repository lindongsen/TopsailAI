"""Keep driver test records inside pytest temporary storage.

Author: DawsonLin
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolate_driver_runtime(monkeypatch, tmp_path):
    """Inject a task-local home without changing the process environment."""
    import session_agent_driver as sad
    monkeypatch.setattr(sad, "TOPSAILAI_HOME", str(tmp_path))
