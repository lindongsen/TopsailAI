---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: done
created: 2026-11-16
resolved: 2026-11-16
---

# A provider step body was JSON-quoted, so a multi-line answer printed as one line

## Trigger

The human reported that `messages` output is unreadable because the content arrives as one long
string on a single line.

Reproduced against the live deployment:

```text
topsailai2 messages ac.ai-dev wa-1fb57b5948b4 -c 400
```

The `topsailai.final_answer` body was printed wrapped in double quotes with every real newline shown
as the two characters `\n`, so a 186-line answer collapsed onto one line.

## Root cause

`providers/topsailai/query.go` wrote the step body with `providerJSONDump`, which is `json.Marshal`.
The provider stores `raw_text` as a JSON **string**, so marshalling produced a quoted, escaped JSON
string instead of the text it held.

Measured on the real provider record for `wa-1fb57b5948b4` (`topsailai session history --json`):

| Measure | Value |
|---|---|
| `raw_text` bytes | 8332 |
| real newlines in `raw_text` | 186 |
| `json.Marshal(raw_text)` bytes | 12140 |
| real newlines after marshalling | 0 |
| marshalled form starts with `"` | yes |

The record shape is `{raw_text: string, step_name: string}`, and a record may arrive either as a bare
object or as a single-element array; `providerStepEntries` already normalizes both.

The renderer was not at fault. `renderStructuredBody` (`internal/tui/messages_body.go`) returns prose
unchanged and only rewrites a body that is still a JSON object or array. The unwrapped text is prose,
so it is printed verbatim, which is correct. The adapter destroyed the line structure before the
renderer saw it.

## Why no test caught it

The BDD and integration layers run the mock Provider, and the mock answers with the
**already-unwrapped** form `topsailai.task\nthe operator wrote this`
(`providers/mock/main.go`, `sessionMessagesResult`). The mock does that deliberately: unwrapping a
provider step record is provider behaviour, so the mock stands in for a provider instead of teaching
the Cluster a record format it does not know. The consequence is that the real Provider's
`unwrapContent` is never reached by those layers. The BDD scenario does declare a real step record, but
that value never reaches the mock Provider, so the assertion passes on the mock's default body, which
happens to equal the expected label and text. That separate defect is recorded in
`issues/bdd-messages-body-injection-never-reaches-the-provider.md`.

The only test that pinned the function was `providers/topsailai/read_test.go`, and it asserted the
quoted form `topsailai.task\n\"hello\"`, so it certified the defect instead of catching it.

## Fix

`providerStepText` writes a string body verbatim and keeps the JSON form only for a non-string value,
because only a string has a plain-text form to prefer. The provider owns the provider's record shape,
so the unwrapping stays here and the renderer stays generic.

The test that pinned the quoted form was replaced rather than supplemented, and three cases were added:
a multi-line body, a non-string body, and a record with extra fields.

## Verification

Suites executed:

```text
make test-provider-topsailai   ok
make test-unit                 ok
make test-bdd                  ok (81.7s)
make test-integration          ok (68.0s)
```

The new tests were proven to fail with the fix reverted:

```text
--- FAIL: TestUnwrapContentKeepsStepBodyLineStructure
    unwrapped="topsailai.final_answer\n\"first line\\nsecond line\\n\\nfourth line\"",
    want "topsailai.final_answer\nfirst line\nsecond line\n\nfourth line"
```

End-to-end proof used the provider built from this tree, driven with a real `session.messages` query
for `wa-1fb57b5948b4`: the `final_answer` body returned 188 lines (186 body newlines plus the step-name
line), zero escaped `\n`, and no leading quote.

## Related conformance failure, resolved separately

At the time of this fix, `make test-provider-topsailai-conformance` also failed on `session.metrics`
and `session.detail` with `query_result must not be null`. That failure was real and unrelated to this
change, but it is no longer reproducible.

The cause was not a missing fixture subcommand, as first recorded here. Two defects combined:

- The conformance suite hardcoded a target for `model.catalog` and `session.messages` only. The two
  newly registered session-scoped queries (`985fcd13`) therefore ran with no target, and the Provider
  correctly rejected them, which read as a Provider defect.
- The fixture answered `call_instruction` with a flat document, so `session.metrics` could not obtain
  the nested `response.result` report it parses.

`1099da3c fix: derive conformance query target rule from registry` fixed both: the target rule now
comes from `providercli.QueryRequiresSessionTarget`, and the fixture answers `agent.tokens` in the
nested envelope. Verified on 2026-11-17 with `make test-provider-topsailai-conformance`, which
reported `ok ... 13.311s`.
