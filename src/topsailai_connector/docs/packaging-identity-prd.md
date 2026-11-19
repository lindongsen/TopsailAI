---
maintainer: AI
author: DawsonLin
status: draft
created: 2026-11-20
updated: 2026-11-20
---

# Packaging-Time Identity Product Requirements

## Document status

This PRD defines the product requirement that a packaged Node must carry a
known node id and a known node credential, decided at packaging time, so the
operator never has to ask the recipient for them after the artifact is
delivered.

The supporting design record is `docs/permission-design.md`, whose "Embedded
configuration" section currently states that the identity and the credential are
**not** embedded. This PRD changes that decision and states why the earlier
objections no longer apply in full.

## Overview

### Background and motivation

A packaged Node is handed to someone else. Today the recipient must run the
binary twice — once with `id` to create the address, once with `credential add`
to create a secret — and then send both values back to the operator before the
operator can reach the machine with the CLI.

That round trip is the problem. It requires the recipient to copy a secret out of
a terminal and transmit it over some channel, it blocks the operator until the
recipient acts, and it fails whenever the recipient is unavailable, non-technical,
or simply forgets. The operator's goal is "ship it, then reach it", and the
current flow makes that impossible.

The requirement is therefore that the packaging step decides the identity and the
credential, records them where the operator can read them, and compiles them into
the artifact so the first start adopts them instead of generating new ones.

### Product goals

- A packaged Node reaches the Server and is addressable by the CLI without any
  action by the recipient.
- The operator learns the node id and the node credential at packaging time, from
  a file the packaging step wrote, not from the recipient.
- The values are recorded in a timestamped env file, `env.{YYYYMMDDHHMMSS}`, so
  several packages built on one day do not overwrite each other's record.
- The embedded values are **seeds, not authorities**: the file on the target
  machine wins once it exists, so `regenerate`, `credential add` and
  `credential remove` keep working unchanged.
- A build that carries a node credential refuses to serve its own executable,
  because the credential is a secret that never expires.
- Packaging without the opt-in behaves exactly as it does today.

### Product non-goals

- Making one package safe to install on several machines at once. One package is
  for one recipient; see "Assumptions and constraints".
- Removing the recipient's ability to regenerate the address or revoke the
  credential. Both remain local acts on the target machine.
- Encrypting the embedded values. A secret compiled into a binary is readable by
  anyone holding the binary; the deny list is what stops a remote reader.
- Letting the recipient widen the blast radius by editing an environment
  variable. The opt-in is a packaging-time decision, recorded in the artifact.
- Replacing the zip bundle. The zip already generates its identity at packaging
  time; this PRD closes the gap in the embedded mode.

### Success measures

- A package built with the opt-in, started on a clean machine, prints the same
  node id and the same credential that the env file records.
- The printed credential authenticates a real CLI call against a real Server on
  the first attempt, with no value typed by the recipient.
- A second start of the same artifact prints the same values and does not
  regenerate them.
- `regenerate` on the target machine changes the address and leaves the
  credential working.
- `credential remove` on the target machine revokes the embedded credential.
- A build without the opt-in produces a byte-identical behaviour to today.

## Personas

| Persona | Goal | Pain today |
|---|---|---|
| Operator who ships a Node | Reach the machine as soon as it connects | Must wait for the recipient to run two commands and report two values |
| Recipient who installs a Node | Start it and be done | Must copy a secret out of a terminal and send it back |
| Operator who ships several Nodes | Keep each package's values apart | No record exists of which package carries which identity |

## User stories

- As an operator, I build a package with the identity embedded, so that I can
  address the Node the moment it connects without contacting the recipient.
- As an operator, I read the node id and the credential from a timestamped env
  file, so that I can configure my CLI without asking anyone.
- As an operator shipping several packages, I get one env file per build, so that
  I never confuse two recipients' credentials.
- As a recipient, I start the artifact and it works, so that I never handle a
  secret.
- As a recipient, I can still regenerate the address and revoke the credential
  locally, so that the embedded values are a starting point rather than a cage.
- As a security reviewer, I see that a build carrying a credential refuses to
  serve its own executable, so that a remote caller cannot read the secret out of
  the file.

## User journey

```
1. Operator builds with the opt-in
   make package PACKAGE_SERVER_URL=... PACKAGE_SCOPES=... \
                PACKAGE_TUNNEL_TOKEN=... PACKAGE_EMBED_IDENTITY=1
   -> bin/connector-node-linux-amd64
   -> bin/env.20261120005539   (mode 0600, holds node id and credential)

2. Operator reads the env file and configures the CLI
   CONNECTOR_CLI_NODE_ID=node_...
   CONNECTOR_CLI_NODE_CREDENTIAL=key_....<secret>

3. Operator hands the artifact to the recipient

4. Recipient starts it
   -> the Node writes the embedded identity and credential on first start
   -> it connects, and the CLI reaches it immediately

5. Later, if the address is exposed
   recipient runs `connector-node regenerate`
   -> new address, credential unchanged, operator updates one variable
```

## Functional requirements

| ID | Requirement |
|---|---|
| FR-PKG-ID-1 | Packaging accepts an opt-in that embeds the node id and the node credential. The opt-in is off by default. |
| FR-PKG-ID-2 | When the opt-in is set, packaging generates the node id and the credential itself, using the Node's own `id` and `credential add` commands, never a second implementation of the formats. |
| FR-PKG-ID-3 | Packaging writes the values to `bin/env.{YYYYMMDDHHMMSS}` with mode `0600`, containing the node id, the key id, the secret, the assembled credential, the Server URL and the CLI variable names. |
| FR-PKG-ID-4 | The env file name carries the build timestamp, so two builds in one day do not overwrite each other. |
| FR-PKG-ID-5 | The embedded node id is written to the identity file on first start when that file does not exist. |
| FR-PKG-ID-6 | The embedded credential is written to the credential file on first start when that file does not exist. |
| FR-PKG-ID-7 | When the file already exists, the file wins and the embedded value is ignored, so `regenerate` and `credential remove` keep working. |
| FR-PKG-ID-8 | A malformed embedded node id or credential fails startup and writes no file, so a bad build is visible rather than silently replaced by a random value. |
| FR-PKG-ID-9 | A build that carries a node credential adds its own executable to the deny list, so a scope containing the binary cannot serve it. |
| FR-PKG-ID-10 | The packaging summary prints the env file path and states that one package is for one recipient. |
| FR-PKG-ID-11 | Packaging without the opt-in produces today's behaviour exactly. |

## Non-functional requirements

- The embedded values are validated by the same `internal/security` functions the
  file path uses, so one definition of a valid node id and a valid credential
  governs both.
- The env file is written with mode `0600` and is never printed to stdout in
  full, because it holds a secret that never expires.
- The env file lives under `bin/`, which is git-ignored, so a credential cannot be
  committed by accident.
- The change is cross-platform: the same packaging script produces the same env
  file for a Linux and a Windows target.
- The seed path adds no new dependency and no new environment variable read
  inside business logic; the seed is resolved once at startup and passed down.
- Startup cost is unchanged: one extra `LoadIdentity`/`LoadCredentials` decision,
  no additional file read on the common path.

## Functional dependencies

| Dependency | Why it matters |
|---|---|
| `internal/security` validators | One definition of a valid node id and credential, shared by the file path and the seed path |
| `internal/node/embedded` | The `-ldflags -X` variables that carry the values into the binary |
| `packaging/build-package.sh` | The only place that can generate the values and write the env file |
| `Makefile` | The only place that can pass the opt-in through to the script |
| `docs/permission-design.md` | States the current "not embedded" decision, which this PRD changes |
| `skills/connector-node-setup` | The only documentation a recipient reads |

## MoSCoW priority

| Priority | Item |
|---|---|
| Must | FR-PKG-ID-1, 2, 3, 5, 6, 7, 8, 9, 11 |
| Should | FR-PKG-ID-4, 10 |
| Could | A `PACKAGE_NODE_ID` / `PACKAGE_NODE_SECRET` override for an operator who must reuse a known value |
| Won't (this release) | Multi-recipient packages, encrypted embedded values, a Server-side registry of packaged identities |

## Release recommendation

Ship as an opt-in packaging feature in the same release as the startup summary.
The default stays off, so an existing build is unaffected, and the feature is
discoverable from the packaging summary and the Node skill.

## Acceptance criteria

- **AC-PKG-ID-1** A package built with `PACKAGE_EMBED_IDENTITY=1` produces
  `bin/env.<timestamp>` at mode `0600` containing the node id, key id, secret and
  assembled credential.
- **AC-PKG-ID-2** The artifact started on a clean machine prints the same node id
  and the same credential the env file records.
- **AC-PKG-ID-3** That credential authenticates a real CLI call against a real
  Server on the first attempt.
- **AC-PKG-ID-4** A second start prints the same values and does not regenerate
  them.
- **AC-PKG-ID-5** `regenerate` on the target changes the address and leaves the
  credential working.
- **AC-PKG-ID-6** `credential remove` on the target revokes the embedded
  credential, and a restart does not restore it.
- **AC-PKG-ID-7** A build carrying a credential refuses `file.read` on its own
  executable.
- **AC-PKG-ID-8** A build without the opt-in behaves exactly as today.
- **AC-PKG-ID-9** A malformed embedded value fails startup and writes no file.
- **AC-PKG-ID-10** Two builds in one day produce two env files, and neither
  overwrites the other.

## Assumptions and constraints

- **One package is for one recipient.** Two copies of one artifact share one node
  id, and the Server keeps an in-memory `node_id -> connection` registry, so the
  second copy to connect evicts the first. Two copies also share one credential,
  so revoking one recipient revokes all of them. Both consequences are stated in
  the packaging summary and in the Node skill rather than prevented, because
  preventing them would require the Server to know which copy is which, which it
  cannot.
- **The embedded values are seeds.** The file on the target machine wins once it
  exists. This is what keeps `regenerate`, `credential add` and `credential
  remove` working, and it is the reason the earlier "regeneration has no file to
  rewrite" objection no longer applies.
- **A secret in a binary is readable by whoever holds the binary.** `-X` stores
  the value as plain text in the data section, so `strings` recovers it. The
  protection that matters is the deny list, which stops a remote caller; a local
  user with the file already has the secret.
- **The env file is a credential record.** It holds a secret that never expires,
  so it is written at mode `0600` under the git-ignored `bin/` directory and is
  never echoed in full by the packaging summary.

## Open questions

- Should `PACKAGE_NODE_ID` and `PACKAGE_NODE_SECRET` be accepted as explicit
  overrides, for an operator who must reuse a value already recorded elsewhere?
  The default is auto-generation, which the human asked for; an override is a
  convenience that adds a second source for one value and therefore needs a
  stated precedence.
- Should the env file also be written in zip mode, which already generates the
  identity but reports it only on stdout?

## Recommended product decisions

- Auto-generate by default, and treat an explicit override as a later addition
  only if a real need appears. The human asked for "自动生成好，然后存一份 env
  文件", which is the simpler contract.
- Write the env file in both modes. The zip mode already generates the values, so
  recording them costs nothing and removes the "read it off stdout" step.
- Keep the opt-in off by default, so the feature cannot surprise an existing
  build.
