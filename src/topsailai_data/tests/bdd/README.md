# topsailai-data BDD tests

The BDD suite executes the compiled CLI as a subprocess. Each scenario uses an isolated data root below `.tmp/bdd/scenarios/`; reports are written below `.tmp/bdd/reports/`.

Run the focused smoke flow with `make bdd-smoke` or run all currently implemented BDD scenarios with `make bdd-test`. The suite intentionally clears inherited `TOPSAILAI_DATA_*` variables before applying deterministic local-adapter settings.

Fixtures that already exist on disk are passed to the CLI through `--from`. Generated test artifacts must remain under `.tmp/bdd`.

The current increment covers the foundational smoke flow plus create, show, and update scenarios. Remaining planned feature groups are not yet encoded and must not be represented as passing coverage.
