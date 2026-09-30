"""Controlled worker fixture."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import wrong_channel


if __name__ == "__main__":
    raise SystemExit(wrong_channel())
