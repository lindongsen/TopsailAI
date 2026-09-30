"""Command-line adapter exposing controlled fake worker modes."""

import sys

from topsailai.tests.unit.test_topsailai_hooks import fake_workers


if __name__ == "__main__":
    mode = sys.argv.pop(1)
    raise SystemExit(getattr(fake_workers, mode)())
