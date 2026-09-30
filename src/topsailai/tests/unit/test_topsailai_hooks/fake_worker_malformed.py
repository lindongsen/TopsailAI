"""Worker fixture that emits a malformed result frame."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import malformed


if __name__ == "__main__":
    raise SystemExit(malformed())
