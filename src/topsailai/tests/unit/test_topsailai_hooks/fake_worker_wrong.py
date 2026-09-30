"""Worker fixture that returns a mismatched correlation identifier."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import wrong_correlation


if __name__ == "__main__":
    raise SystemExit(wrong_correlation())
