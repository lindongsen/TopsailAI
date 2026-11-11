# topsailai-data BDD tests

The BDD suite executes the compiled CLI as a subprocess. Each scenario uses an
isolated data root below `.tmp/bdd/scenarios/`; reports are written below
`.tmp/bdd/reports/`.

Run the focused smoke flow with `make bdd-smoke` or run all implemented BDD
scenarios with `make bdd-test`. The suite intentionally clears inherited
`TOPSAILAI_DATA_*` variables before applying deterministic local-adapter
settings.

Fixtures that already exist on disk are passed to the CLI through `--from`.
Generated test artifacts must remain under `.tmp/bdd`.

## Implemented feature groups

| Feature file | Coverage |
|---|---|
| `smoke.feature` | Create, list, and show the minimal end-to-end flow. |
| `create.feature` | Explicit and frontmatter descriptions, tags, classify paths, stdin input, invalid frontmatter, empty input, duplicate rejection. |
| `show-update.feature` | Show metadata plus markdown and user files, update and clear a description, reject updates on deleted or ceased objects. |
| `list-search.feature` | Empty structural output, pagination, both time sort directions, name/tag/classify matching, OR queries, invalid query syntax, deleted visibility, invalid output options. |
| `tag-move.feature` | Add, remove, and idempotent tag operations; move preserving identity, timestamps, markdown, and extra data; rejection on non-active and unknown objects. |
| `lifecycle-gc.feature` | Soft delete visibility, show for deleted and ceased objects, recover, ceased data rejection, dry-run GC, targeted GC, retention window, invalid GC status. |
| `file-tool.feature` | The complete `file` command group: read windows, line ranges, context matching, multi-file reads, writes, inserts, appends, existence checks, folder creation, listings, sizes, line replacement, stdin precedence, and user payloads named like metadata markers. |
| `file-archive-marker.feature` | Archive updates preserving or replacing the mandatory Markdown marker. |
| `archive-overlap.feature` | Rejecting archive sources that overlap the target object for `put-archive` and `recover --from`. |
| `same-file-input.feature` | Rejecting a `put` source that is the destination file. |
| `store-layout.feature` | Fresh-store initialization, unmarked non-empty root rejection, hashed metadata with a separate tags file, relative data references, and no classify tag inheritance. |
| `stat.feature` | Read and write counting, list/search not changing counters, frozen statistics while deleted, `stat top` ranking, `--with-stat` attachment, and invalid `stat top` options. |
| `binary-recovery.feature` | Byte-exact binary round trip through `put` and `get`, `recover --from` with an external archive, and overlap rejection preserving deleted status. |
| `non_smoke.feature` | Tag selection sanity check for the non-smoke subset. |

## Scenario and step counts

The suite currently runs 119 scenarios and 794 steps, all passing. Counts are
recorded from an executed run, not estimated.

## Adding a scenario

1. Add or extend a `.feature` file under `features/`.
2. Register any new step text in `suite_test.go` or a dedicated step file.
3. Keep every assertion on observable CLI output or on documented on-disk
   contracts, never on internal implementation details.
4. Run `make bdd-test` and confirm the reported scenario and step counts.

## Known gaps

The following behaviors are covered by unit tests or the manual/live plan
instead of BDD, because they need process-level fault injection, real
concurrency, or destructive isolation:

- Advisory lock contention and namespace lock serialization.
- Concurrent statistic updates under load.
- Filesystem fault injection such as permission denial or a read-only volume.
- Large-scale listing and search timing.
- Terminal interactive prompting.

Do not represent these as BDD-covered.
