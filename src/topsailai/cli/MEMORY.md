# Memory

Facts and decisions the human directed to be recorded for this project. AI self-learned lessons
belong in `LEARN.md`, not here.

## Compiled builds turn top-level CLI scripts into executables, never modules

Directed by the human on 2026-11-23: compiled-build behavior must be recorded in project memory,
because it changes what the shipped artifact can do and it has already caused a production crash.

The mechanism is recorded once in `LEARN.md` under "A top-level CLI script is an executable in a
compiled build, never a module": the packager decides the artifact kind from the first line of each
file, so a shebang-bearing script becomes a standalone executable and a file without it becomes an
importable `.so`. That entry is the single source of truth for how the artifact kind is decided; do
not restate the mechanism here.

What this project must therefore preserve:

1. Production code MUST NOT import a top-level CLI script, even when the import works from the source
   tree. Shared logic belongs in a `cli_topsailai` module; one script invokes another through its
   installed command or an explicit process boundary.
2. A source-tree import test proves nothing about the artifact. `tests/unit/topsailai/test_compiled_layout_import_guard.py`
   holds the guard: it rejects static imports of shebang-bearing scripts and imports every package
   module in a child process where those script names are blocked.

## The compiled package also compiles the session agent driver

`build/build.yaml` sets `include: topsailai/` with `lib_home: /TopsailAI/src`, which covers
`topsailai/scripts/` as well. Because `scripts/session_agent_driver/session_agent_driver.py` carries a
shebang, a compiled install ships `session_agent_driver` without the `.py` suffix and never ships the
source file.

Consequences that must be preserved:

1. Driver resolution prefers the compiled sibling entry and runs it directly with no Python
   interpreter, so a compiled install needs no interpreter at all.
2. Error guidance must name the installation kind it actually observed. A compiled install must never
   be told to install `session_agent_driver.py`, because that path does not exist in the package; it
   must be told to reinstall the package instead.
3. `sys.executable` names the compiled CLI binary rather than an interpreter, so it is not a usable
   interpreter candidate in a compiled install. An absent runtime candidate is not evidence of a
   compiled install and keeps the generic interpreter guidance.
