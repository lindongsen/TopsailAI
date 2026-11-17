---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-17
---

# Command admission accepts an unregistered endpoint and leaks the SQLite error

## Symptom

`POST /api/v1/commands` for an Endpoint that was never registered returns a 400 whose message is
the raw SQLite error text:

```text
status=400 {"code":"admission_failed","message":"constraint failed: FOREIGN KEY constraint failed (787)"}
```

Every read path answers the same condition with `404 endpoint_not_found`. One condition therefore
has two status codes, two codes and two messages depending on which route the caller used, and the
admission answer exposes an internal storage implementation detail.

## Root cause

`admitCommand` (`internal/server/commands.go:201`) does not call `requireRegisteredEndpoint`. The
read paths do:

| Path | Endpoint existence checked |
|---|---|
| output snapshot / follow | yes (`http.go:171,225`) |
| messages / history / detail / model / metrics | yes, each returns `endpoint_not_found` |
| command admission `admitCommand` | **no** |

The only thing that currently refuses the request is the database foreign key constraint, which is
why the caller sees a storage error instead of a routing error. That is an accidental guard, not a
designed one: it depends on `foreign_keys` being active on the connection that handles the insert.

Before `fix: enforce sqlite foreign keys on every pooled connection`, the guard disappeared entirely
after a connection discard, and the command was stored silently:

```text
foreign_keys after discard = 0
AdmitCommand error = <nil>
orphan command rows = 1
```

With the DSN pragma in place the row is refused again, but the refusal is still reported as a
storage failure rather than as an unknown Endpoint.

## Why it matters

- **Wrong diagnosis.** A caller who mistyped an Endpoint ID is told that a constraint failed. The
  natural next step is to investigate the database, not the identifier.
- **Inconsistent contract.** The same condition returns `404 endpoint_not_found` on every read and
  `400 admission_failed` on admission, so a client cannot handle "no such machine" with one branch.
- **Information disclosure.** The message carries the SQLite error code and the constraint name,
  which is storage-layer detail that no API contract promises.
- **Fragile safety.** The refusal depends on a database setting rather than on an explicit check, so
  any future change to connection handling or to the schema silently removes it.

## Required correction

Call `requireRegisteredEndpoint` in `admitCommand` before persisting the intent, so an unknown
Endpoint is refused with the same `404 endpoint_not_found` the read paths return. Keep the foreign
key as defence in depth; it must not be the only guard.

Add a test that admits a command for an unregistered Endpoint and asserts the response code is
`endpoint_not_found` rather than `admission_failed`, and that no command row is written.

## Scope note

This is a separate defect from the missing DSN pragma. The pragma fix restores referential
integrity; this issue is about which layer answers the refusal and how it is reported. They were
kept as separate logical units so each change stays reviewable on its own.

## Resolution

Fixed in `a4831c3e`.

`admitCommand` (`internal/server/commands.go:225`) now calls `requireRegisteredEndpoint` immediately
after the issuer check and before the intent is hashed or persisted. An unknown Endpoint is refused
with `404 endpoint_not_found`, the same code every read path returns, so one condition has one status
code and the caller can handle "no such machine" with a single branch. The foreign key on the command
table remains as defence in depth; it is no longer the only guard.

The raw SQLite text no longer reaches the caller on this path. The tests assert the body does not
contain `FOREIGN KEY` or `constraint failed`, so a future regression that removes the guard fails on
the message as well as on the status code.

### Tests

`internal/server/commands_admission_endpoint_test.go`:

- `TestCommandAdmissionRefusesUnregisteredEndpoint` asserts `404` with `endpoint_not_found` and
  asserts the body carries no storage-layer detail.
- `TestCommandAdmissionRefusesUnregisteredEndpointWithoutWriting` asserts no command row is stored
  for a refused admission.
- `TestCommandAdmissionStillAcceptsRegisteredEndpoint` is the paired positive case, so the two
  negative tests cannot pass by admission being disabled altogether.

### Verification

```
go test ./internal/server/ -run 'TestCommandAdmission' -v
--- PASS: TestCommandAdmissionRefusesUnregisteredEndpoint (0.07s)
--- PASS: TestCommandAdmissionRefusesUnregisteredEndpointWithoutWriting (0.05s)
--- PASS: TestCommandAdmissionStillAcceptsRegisteredEndpoint (0.10s)
--- PASS: TestCommandAdmissionForwardsRegardlessOfDeclaredPermission (0.08s)
--- PASS: TestCommandAdmissionForwardsUndeclaredControlOperation (0.09s)
--- PASS: TestCommandAdmissionKeepsStandardOperationAdmissible (0.06s)
--- PASS: TestCommandAdmissionStillRejectsIssuerMismatch (0.07s)
--- PASS: TestCommandAdmissionIsIdempotentAndConflicts (0.06s)
ok  topsailai_agent_cluster/internal/server  0.595s
```

Full package: `ok topsailai_agent_cluster/internal/server 2.889s`. `go vet` clean, `gofmt -l` clean.

### Deliberate breakage

Removing the guard reproduced exactly the defect this issue describes, which proves the tests can
distinguish the two behaviours rather than passing by construction:

```
status=400 want=404 body={"code":"admission_failed","data":null,
  "message":"constraint failed: FOREIGN KEY constraint failed (787)",...}
--- FAIL: TestCommandAdmissionRefusesUnregisteredEndpoint (0.08s)
--- FAIL: TestCommandAdmissionRefusesUnregisteredEndpointWithoutWriting (0.05s)
```

Both failures name the behaviour. The guard was restored and the suite re-run green before commit.

### Limitation

The refusal is now explicit, but the foreign key is still the only protection for any future write
path that forgets the check. That is the intended defence-in-depth arrangement, not a gap in this
fix.
