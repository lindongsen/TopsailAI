---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Two messages round-trip integration tests disagree with the renderer and the fixture

## Trigger

Found while running `make test-integration` to verify the human-readable CLI time change. Both
failures reproduce at HEAD `e735260e` in a detached worktree with none of that change present, so
they are pre-existing defects rather than regressions from the time-rendering unit.

## Observed behavior

```text
--- FAIL: TestMessagesRoundTripMaxChars (2.93s)
    messages_roundtrip_test.go:124: bounded content "fixture message body"
--- FAIL: TestMessagesRoundTripStandaloneCLI (4.08s)
    messages_roundtrip_test.go:230: rendered conversation missing content:
        #1 - Role: USER - Words: 20 - Tokens: 3 - 2026-11-09 10:00:00.000
        fixture message body
```

## Root cause

Two independent defects, both in the test layer rather than in the product.

### The role assertion contradicts the renderer on purpose

`messagesRoleCell` (`internal/tui/messages.go:352-357`) uppercases the provider's speaker word:

```go
return strings.ToUpper(clean)
```

`TestMessagesRoundTripStandaloneCLI` asserts `containsAll(stdout, "fixture message body", "user",
"assistant")` (`tests/integration/messages_roundtrip_test.go:229`), so it requires the lowercase
form. The rendered output contains `Role: USER` and `Role: ASSISTANT`, which is the intended
behaviour: the role is a safe inline token rendered as a label. The assertion is stale, and it fails
on the casing while the content it also checks is present.

### The fixture never implements the character bound

`MaxChars` is documented as applied by the adapter (`internal/protocol/messages.go:10`), and the
Server forwards it (`internal/server/messages.go:56`). The Go fixture
`tests/fixtures/topsailai_fixture/main.go:134-146` builds each message body and emits it unchanged;
it contains no `max_chars` handling at all. `TestMessagesRoundTripMaxChars` therefore requests
`max_chars=5` and receives the complete body, so the test asserts a provider behaviour the fixture
does not model.

## Why this matters

`TestMessagesRoundTripMaxChars` is the only integration coverage of the per-message character bound
travelling from HTTP through the Server, the channel and the adapter to the provider. Because the
fixture ignores the bound, the test cannot pass, and the bound's end-to-end behaviour is unverified
at the integration layer. The unit test `TestMessagesMaxCharsReachesTheEndpoint`
(`internal/server/messages_test.go:261`) proves only that the Server forwards the value, not that it
changes the returned body.

## Suggested fix

- Change the role assertion to the rendered uppercase form, or assert case-insensitively, so the
  test states the renderer's actual contract.
- Teach the fixture to apply `max_chars` the way the real provider does: shorten the body and append
  an ellipsis, so `max_chars=5` yields `fixtu...`. The test comment already describes exactly that
  behaviour, so the fixture is what is missing.

## Verification

```text
git worktree add --detach /tmp/headcheck e735260e
go test -count=1 -tags "integration testhooks" \
  -run 'TestMessagesRoundTripMaxChars|TestMessagesRoundTripStandaloneCLI' ./tests/integration/
# both FAIL at HEAD, before any change from the time-rendering unit
```
