---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-14
resolved: 2026-11-14
---

# The documented `node-id.node-token` format disagreed with the implementation

## Symptom

`docs/permission-design.md` described the pair in a grammar that the code does not
implement:

```text
node-id    = "node_" 1*( ALPHA / DIGIT / "-" )      no dots, no underscores
node-token = 32*64 ( ALPHA / DIGIT / "-" / "_" )   base64url, no dots
```

The implementation in `internal/security/identity.go` uses unpadded lowercase
base32 with fixed lengths:

| Property | Documented | Implemented |
|---|---|---|
| Alphabet | `ALPHA / DIGIT / "-" / "_"` | `a-z` and `0-9` only |
| Encoding | base64url | unpadded lowercase base32 |
| `node-id` body length | `1*`, at least one character | exactly 26 |
| `node-token` length | `32*64` | 52 generated, not validated |

Measured on the real binary:

```text
$ ./bin/connector-node id
node_oswngej2n7glyprc3cljp6an4i.br4l25x274uyk4wej5s42ss6kpqtb4vhevxwxmwczhrhfmawxnkq
```

`node-id` is 31 characters, the token is 52, the pair is 84.

## Impact

The code was correct and the documentation was wrong, so nothing failed at
runtime. The damage was to anyone reading the document:

- A client written against the documented grammar accepts `-` and `_`, then is
  refused by the Node with `malformed node-id.node-token pair`. The failure
  appears at authentication, far from the document that caused it.
- A client written against `32*64` rejects the 52 character token the Node
  actually generates.
- A reader concludes the alphabet is negotiable, because the document says
  base64url and the code says base32. It is not negotiable: the alphabet is what
  makes the value survive a URL, a shell argument and a Windows file name.

The same defect reached `docs/cases/TestCase_node-id-pair.md`, where it was worse
than a wrong description. Every case in that file used an 8 character identifier
body, so:

- `TC-PAIR-1`, the case that asserts a well-formed pair is **accepted**, used a
  pair the parser **refuses**. The case asserted the opposite of the truth.
- Every other case was refused by the length check before reaching the rule it
  claimed to test. A test written from those cases would have passed for the
  wrong reason.
- `TC-PAIR-13` claimed a 100 KiB pair is refused as unbounded. The parser has no
  length limit and accepts it.

## Root cause

The document was written before the implementation and was never reconciled with
it. The grammar block was a design sketch: `ALPHA / DIGIT / "-"` and `32*64` are
plausible-looking placeholders rather than values derived from anything.

The implementation then made three decisions the document never recorded:

1. **Base32 instead of base64url.** `-` and `_` are URL-safe but not
   shell-safe or Windows-filename-safe, and uppercase is excluded because Windows
   compares paths case-insensitively.
2. **A fixed identifier length.** `nodeIDBodyLength` is derived from the entropy
   (`ceil(16 * 8 / 5)`), so a truncated identifier fails at parse time instead of
   producing a Node that can never be addressed.
3. **No token length check.** A token of an unexpected length is still
   comparable, so the comparison fails and the request is refused. Checking the
   length would also break a token from an older build with different entropy.

None of the three was written down, so the document kept describing the sketch.

## Detection failure

`issues/done/issue-node-id-length-not-enforced.md` fixed the identifier length
check and quoted the design document's "128 bits ... 26 characters of unpadded
base32" as the authority. That quote was correct, and it sat in the same document
as the wrong grammar block twenty lines above. Nobody compared the two.

The test-case file was never executed. It is prose, so no test runner reads it,
and its examples were never fed to `ParseNodeIdentity`. A single call would have
shown that `TC-PAIR-1` asserts a refusal as an acceptance.

## Fix

Documentation only. The implementation was already correct and is unchanged.

- `docs/permission-design.md`: the grammar now states `26( LOWER / DIGIT )` and
  `52( LOWER / DIGIT )`, with a table deriving both lengths from the entropy. The
  alphabet choice is explained, the identifier length rule is added to the
  parsing list, and the deliberate absence of a token length check is stated with
  its reason.
- `docs/cases/TestCase_node-id-pair.md`: every example now uses an 84 character
  pair, so each case tests the rule it names. `TC-PAIR-1` asserts an acceptance
  that the parser actually produces. Three cases were added: the identifier
  length rule, the alphabet rule, and the fact that the token length is not
  validated. The 100 KiB case now states the truth: the parser accepts it and the
  transport bounds it.
- `docs/cases/README.md`: the case count for that file is 33, and the total is
  505.
- Abbreviated examples in `docs/API.md`, `docs/permission-design.md`,
  `skills/connector-node-setup/SKILL.md` and `skills/connector-client/SKILL.md`
  used uppercase `kQ2v`, which the parser rejects. They are lowercase now.

## Verification

Every claim in the rewritten documents was checked against the running code, not
against the previous document:

| Claim | How it was checked |
|---|---|
| The generator emits 31 + 52 characters | `./bin/connector-node id` on the real binary |
| `-` and `_` are refused | `ParseNodeIdentity` called with each; both refused |
| Uppercase is refused | `ParseNodeIdentity` with `B` in the token; refused |
| An 8 character identifier body is refused | `ParseNodeIdentity`; refused, naming the length |
| A 5 character token is accepted | `ParseNodeIdentity`; accepted |
| A 100 KiB token is accepted | `ParseNodeIdentity`; accepted |
| The example pair in the cases is accepted | `ParseNodeIdentity`; accepted, token length 52 |
| The transport bound is the listener's | `internal/server/listener.go` sets no `MaxHeaderBytes`, so Go's 1 MiB default applies |

The probe tests used for this were temporary and were removed after the run. The
format is now pinned by `internal/security/identity_format_test.go`, which asserts
the documented lengths as literals rather than through the validator constants, so
a change to the entropy or the encoding fails the test instead of silently
changing the format. Two mutations were used to confirm the test can fail: raising
`nodeIDRandomBytes` from 16 to 20 produced `len(id) = 37, want 31`, and switching
the encoding to base64url produced `len(token) = 43, want 52` plus
`token contains '_', which is not in a-z0-9`.

## Prevention

- A grammar block in a design document is a claim about the implementation. It
  must be derived from a constant in the code, or it must cite the constant it
  mirrors, so a change to the entropy cannot leave the document describing a
  length the generator no longer produces.
- A test-case document whose examples are never executed is prose. At minimum,
  the "well-formed" example must be fed to the real parser once, because that is
  the one case where a wrong example inverts the assertion.
- When a document states a length, state the derivation next to it. `52` alone
  invites a later edit; `ceil(32 * 8 / 5)` does not.
- A test that pins a format must assert literals, not the constants it is meant to
  pin. `len(id) == nodeIDBodyLength` moves with the constant, so it stays green
  while the format changes.
- A test that samples one generated value can pass by luck. The first version of
  the alphabet test sampled one identity and stayed green under a base64url
  mutation, because base64url emits `-` or `_` in only a small fraction of values.
  It now samples 200.
