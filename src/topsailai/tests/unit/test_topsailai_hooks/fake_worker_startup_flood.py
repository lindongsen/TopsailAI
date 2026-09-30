"""Controlled worker fixture."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import startup_flood


if __name__ == "__main__":
    raise SystemExit(startup_flood())
