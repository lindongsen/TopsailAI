"""Controlled worker fixture."""

from topsailai.tests.unit.test_topsailai_hooks.fake_workers import no_read


if __name__ == "__main__":
    raise SystemExit(no_read())
