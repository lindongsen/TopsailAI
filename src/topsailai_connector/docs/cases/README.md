---
maintainer: AI
author: DawsonLin
---

# Test Cases

The cases are split by area rather than collected in one file, because a single
file of two hundred rows is a file nobody reads before a change. Each file covers
one boundary, so a reviewer touching that boundary reads one file.

## Index

| File | Area | Prefix | Cases |
|---|---|---|---|
| `UserCase_identity-and-access.md` | What an operator is trying to do | `UC-` | 8 |
| `TestCase_secret-gates.md` | The three secrets and what each one gates | `TC-SEC-` | 28 |
| `TestCase_node-id-pair.md` | The `node-id.node-token` pair: format, parsing, regeneration | `TC-PAIR-` | 33 |
| `TestCase_node-authority.md` | The Node as the only authority: scope and permission control | `TC-NODE-` | 52 |
| `TestCase_operations.md` | `file.list`, `file.stat`, `file.read` semantics, depth and path length | `TC-OP-` | 56 |
| `TestCase_policy-and-scope.md` | Policy file validation and scope mapping | `TC-POL-` | 54 |
| `TestCase_cli-and-routing.md` | CLI surface, routing, `node-id` agreement | `TC-CLI-` | 38 |
| `AdversarialCase_path-fence.md` | Attempts to read outside a scope | `AC-PATH-` | 66 |
| `AdversarialCase_node-authority.md` | Attempts to move the authority off the Node | `AC-NODE-` | 70 |
| `AdversarialCase_secrets.md` | Attempts to defeat or extract a secret | `AC-SEC-` | 52 |
| `AdversarialCase_windows-paths.md` | Windows-specific name hazards, junctions at depth | `AC-WIN-` | 48 |

505 cases in total. The adversarial files are the larger half on purpose: a
read-only system has one real boundary, so that boundary gets the most cases.

The Node-authority pair is the second-largest group, because the authority is the
thing the whole design exists to protect. `TestCase_node-authority.md` checks that
the Node exercises it; `AdversarialCase_node-authority.md` checks that nothing
outside the Node can move it, including a compromised Server.

## Conventions

Every case has an identifier, a precondition, an action and an expected result.
The expected result is stated as an observable outcome, not as an internal state,
because a test that asserts an internal field passes while the wire behaviour is
wrong.

A refusal is always stated with its error code, so a case cannot pass by refusing
for the wrong reason. "Refused" alone is not an expected result: a request that
fails because the Node is offline has not tested the fence.

## Layers

| Layer | Where | What it proves |
|---|---|---|
| Unit | `internal/*/**_test.go` | One function, no IO |
| Integration | `tests/integration/` | Server and Node over a real socket |
| BDD | `tests/bdd/` | A user story end to end |
| End-to-end | `tests/e2e/` | Two real processes over a real socket, driven by `make check` |
| Manual | a real Windows host | A platform behaviour that cannot be automated on this host |

Every script under `tests/e2e/` is automated: each one picks its own port, starts
and stops its own processes by exact PID, and exits non-zero on failure, so
`make check` runs all of them. The only case that needs a human is
`windows_deep_nesting.sh`, which must run on a real Windows host because wine
resolves paths through the Linux filesystem and therefore does not enforce
`MAX_PATH`. Its evidence is recorded in `docs/permission-design.md` rather than
asserted by a test that cannot run here.

The adversarial cases are unit, integration and end-to-end cases, not manual ones.
A path escape is a deterministic input, so it belongs in a test that runs on every
commit rather than in a checklist a human follows.

## What is not covered here

- TLS certificate validation. It is the standard library's job and a test of it
  would test Go rather than this project.
- Host compromise. The design states plainly that nothing in it helps once the
  Node's host is lost, so there is no case for it.
- Performance. The scale assumptions belong in the design document, and a timing
  assertion in a unit test is a flaky test.

## Related documents

- `docs/permission-design.md` — the contract these cases verify.
- `docs/API.md` — the error codes referenced by the expected results.
- `docs/Environment_Variables.md` — the configuration each case sets up.
