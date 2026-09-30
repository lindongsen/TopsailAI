"""Controlled worker fixture."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import late_result


if __name__ == "__main__":
    raise SystemExit(late_result())
