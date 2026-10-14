"""Compatibility child entry point for history replay BDD execution."""

from tests.bdd.history_replay_metadata_harness import _CHILD


if __name__ == "__main__":
    exec(compile(_CHILD, __file__, "exec"), globals(), globals())
