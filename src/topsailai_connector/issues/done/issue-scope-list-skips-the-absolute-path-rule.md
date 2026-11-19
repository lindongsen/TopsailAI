---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# The absolute-path rule for a scope lived in the fence, so a reader that does not open scopes never applied it

## Symptom

`connector-node scope list` printed a scope name that `connector-node run` refuses
to serve. The command exists to tell an operator what to pass as `--scope`, so
printing a name the Node will not serve is worse than printing nothing: the caller
fills `--scope` with it and receives `denied` from a Node whose policy names the
scope.

## Reproduction

A policy whose scope path is relative:

```yaml
version: 1
scopes:
  project:
    path: rel/path
grants: []
```

Before the fix, `connector-node scope list` printed `project` and exited 0, while
`connector-node run` refused to start with
`scope "project": path "rel/path" is relative; a relative path resolves differently per launch`.

## Impact

The command's own doc comment promised that the answer is "exactly the set the Node
would serve, not a second list that could drift from it". A relative path broke that
promise silently, because the two readers disagreed about what a valid policy is.

The blast radius was small — a relative scope path is a policy authoring mistake, and
`packaging/start.sh` and `packaging/start.ps1` both resolve relative scope paths to
absolute before writing `policy.yaml`, so neither delivery path emits one. But the
divergence was real and the class of defect is the one that matters: two readers of
one document disagreeing about its validity.

## Root cause

`docs/permission-design.md` lists "Every scope needs an absolute `path`" as a policy
validation rule, and the enforcement checklist repeats it. The check was implemented
only in `internal/node/fence.go` `OpenScope`, which is reached by `run` when it opens
each scope.

`LoadPolicyForListing` deliberately does not open scopes, because opening them applies
the fence's startup rules and would make a listing fail on a machine where a scope
directory is absent — exactly when the operator needs the names. So the listing path
never reached the check, and the rule was enforced for one reader and not the other.

This is the failure mode `LEARN.md` already records as "A rule stated only in prose is
not implemented": a rule documented, reviewed and half-enforced at the same time.

## Detection failure

The new tests were written against the behaviour the command was supposed to have, and
one of them — `TestListScopeNamesRejectsAMalformedPolicy` — used a relative path as its
malformed document. It failed on the first run, which is the only reason the gap was
found. Reading the diff would not have found it: `LoadPolicyForListing` reads correctly
on its own, and the fence reads correctly on its own.

The general lesson is that a second reader of a document needs the document's
validation, not just its parser. Sharing the decoder is not enough when a rule lives in
the consumer.

## Fix

Moved the rule into the decoder, so every reader applies it:

```go
if !filepath.IsAbs(definition.Path) {
    return nil, fmt.Errorf("scope %q: path %q is relative; a relative path resolves differently per launch", name, definition.Path)
}
```

in `parseScopes` in `internal/node/policy/policy.go`, plus the `path/filepath` import.

The fence keeps its own check. That is deliberate duplication of a refusal, not of a
rule: the fence's message names the fence, and a policy decoded from bytes that never
touched `parseScopes` would still be refused at open time. Both refusals are
fail-closed, so the duplication cannot produce a disagreement about whether to serve.

## Verification

- `TestListScopeNamesRejectsAMalformedPolicy` and
  `TestRunScopeListRejectsAMalformedPolicy` both pass, and both assert the message
  contains `is relative` rather than only that an error occurred.
- Mutation: removing the decoder check makes both tests fail. Restored, and the file's
  md5 compared with the backup.
- All existing policy tests use absolute paths, so the new refusal changed no existing
  expectation.
- `go test ./... -count=1` green across all 14 packages; `go vet ./...` and
  `gofmt -l cmd/ internal/` clean.
- Measured on the real binary: a relative scope path now exits 1 with
  `connector-node: scope "project": path "rel/path" is relative; a relative path resolves differently per launch`.
