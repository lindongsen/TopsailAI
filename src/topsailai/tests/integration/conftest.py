"""Integration-test configuration.

The artifact-ancestry validator rejects world-writable ancestry (``mode & 0o022``),
and pytest's default ``tmp_path`` lives under ``/tmp`` (mode 1777). Route the
integration temp tree to a workspace-scoped root under ``.tmp`` instead, unless
the caller already supplied an explicit ``--basetemp``.
"""
import pathlib


def pytest_configure(config):
    """Route integration temp trees to a workspace-scoped, validator-compliant root."""
    if not config.option.basetemp:
        config.option.basetemp = str(pathlib.Path("/TopsailAI/src/topsailai/.tmp/pytest-int"))
