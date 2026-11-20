---
maintainer: AI
author: DawsonLin
status: draft
created: 2026-11-20
updated: 2026-11-20
---

# Read-Only-Filesystem Mode and In-Process Console Product Requirements

## Document status

This PRD defines two additive product requirements:

1. A Node that starts without creating any directory or file, using only the
   configuration compiled into the binary, so it can run on a read-only
   filesystem.
2. An interactive console inside the running Node process that reads
   configuration and credential information and regenerates the node id and the
   credentials, entirely in memory.

The supporting design record is `docs/permission-design.md`. Its "Embedded
configuration" section currently states that the identity and the credential are
written to files on first start, and its "Scope to directory mapping" section
states that a scope must not overlap the config directory. This PRD adds a mode
in which there is no config directory at all, and states what that changes and
what it does not.

The user stated the incremental constraint explicitly:

> 我提的需求都是增量式开发，不要去删掉以前支持的功能。

Every requirement below is therefore additive. The file-based mode remains the
default, and no existing subcommand, flag, environment variable, help page, skill
section or test is removed to make room for either feature.

## Overview

### Background and motivation

A Node currently requires a writable configuration directory. `resolveConfigDir`
creates it with mode `0700` when it is missing, and `Open` then writes two files
into it, `identity` and `credentials.yaml`, before the Node can serve anything.
On a read-only filesystem, a locked-down home directory, or a container with an
immutable root, the Node refuses to start:

```text
create CONNECTOR_NODE_CONFIG_DIR "<path>": mkdir <parent>: no such file or directory
```

That refusal is correct for the current design, because the running Node adopts a
regenerated node id by polling the identity file, and `regenerate`,
`credential add` and `credential remove` all work by rewriting those two files. A
Node with no writable directory therefore has no way to change its address or its
credentials.

Two requirements follow. The first is that such a Node must be able to start at
all. The second is that it must not lose the ability to change its address and
its credentials, because that ability is what makes a Node recoverable when an
address is exposed or a secret is suspected.

The second requirement is not limited to the read-only case. An operator who is
already at the machine wants to ask the running process what it is doing and to
change its address without opening a second terminal, editing a file, and waiting
for a poll. The console answers that question in both modes.

### Product goals

- A Node starts and serves on a filesystem it cannot write to, using only the
  configuration compiled into the binary.
- No directory and no file is created anywhere when the mode is enabled.
- The operator can read the Node's configuration, identity, credential key
  identifiers, scopes and channel status from inside the running process.
- The operator can regenerate the node id and add, rotate or remove a credential
  from inside the running process, with no file edited and no file created.
- A regeneration performed in the console takes effect without a restart, and
  drops the channel authenticated under the retired identity.
- The console works in both modes: with files present, a change is also durable;
  without files, it is memory only.
- Every existing behaviour is unchanged when neither feature is enabled.

### Product non-goals

- Detecting whether a filesystem is read-only. The mode never writes, so it
  cannot fail on a write; a detection step would add a failure path that answers
  a question the mode does not ask.
- Replacing the file-based mode. It stays the default and stays fully supported.
- Replacing `regenerate` or the `credential` subcommands. They keep operating on
  files and are not silently redirected to memory.
- Changing the tunnel token or the policy from the console. The tunnel token is a
  Server-side value, and the policy is a whole document that a partial edit would
  leave unreasonably.
- Adding a third-party dependency. Nothing here requires one, and
  `golang.org/x/sys/windows` remains unapproved.
- Fixing the four open security items. They are recorded separately and are not
  changed by this document, except that two of them do not apply in this mode.

### Success measures

- On a filesystem the process cannot write to, the Node starts, connects and
  serves `file.read`, `file.list` and `file.stat`.
- After a full session in the mode, no file and no directory exists under the
  configured path, and the path was never created.
- With the mode unset, the existing test suite passes unchanged and the startup
  summary is byte-identical.
- `show credentials` output contains no secret, verified by searching the output
  for the known secret.
- A console `regenerate id` changes the address, the old address returns
  `node_offline`, and the same credential still authenticates under the new
  address.
- A console change made in file mode survives a restart.

## Personas

| Persona | Goal | Pain today |
|---|---|---|
| Operator running a Node on an appliance | Serve files from a machine whose root filesystem is immutable | The Node refuses to start because it cannot create its config directory |
| Operator running a Node in a container | Run with a read-only root and no writable volume | Must mount a writable volume purely to hold two small files |
| Operator at the machine | Ask the running Node what it is doing | Must read a log file, or run a second command that reads the files |
| Operator who suspects an exposed address | Change the address immediately | Must run a separate command, which needs a writable directory |
| Security reviewer | Confirm no secret is printed by a read command | Must read the source, because no command states what it prints |

## User stories

- As an operator on a read-only filesystem, I start the Node with the mode
  enabled, so that it serves without needing a writable directory.
- As an operator, I confirm from the startup summary which mode the Node is in,
  so that I do not mistake a memory-only Node for a durable one.
- As an operator, I ask the running Node for its identity, its credential key
  identifiers and its scopes, so that I can answer a question without reading a
  file or a log.
- As an operator, I regenerate the node id from the console, so that an exposed
  address is replaced without a restart and without editing a file.
- As an operator, I add or remove a credential from the console, so that I can
  revoke a caller on a machine with no writable directory.
- As an operator in file mode, I use the console and my change survives a
  restart, so that the console is a second way to reach the same state rather
  than a second, weaker state.
- As a security reviewer, I see that `show credentials` prints key identifiers
  only, so that a read command cannot leak a secret.
- As a security reviewer, I see that the mode still refuses the running
  executable when the build carries a tunnel token, so that the mode does not
  quietly remove a protection.

## User journey

```text
1. Operator builds a self-contained Node
   make package PACKAGE_SERVER_URL=wss://host/channel \
                PACKAGE_SCOPES='data=/srv/data' \
                PACKAGE_TUNNEL_TOKEN=<secret> \
                PACKAGE_EMBED_IDENTITY=1
   -> bin/connector-node-linux-amd64
   -> bin/env.20261120090000   (node id, key id, secret)

2. Operator starts it on a read-only filesystem
   CONNECTOR_NODE_STATELESS=1 CONNECTOR_NODE_CONSOLE=1 \
     ./connector-node-linux-amd64 run
   -> mode: stateless (no directory, no file)
   -> node id, credential and CLI block printed
   -> console prompt

3. Operator asks the running process
   > show identity
   > show credentials
   > show scopes
   > show status

4. The address is exposed
   > regenerate id
   -> new node id printed, channel dropped, reconnected under the new id
   -> the credential still works; the operator updates one CLI variable

5. A caller must be revoked
   > credential remove --key-id old-caller
   -> removed in memory; the last credential cannot be removed

6. Operator stops the Node
   > quit
   -> channel closed, exit status 0
```

The same console works in file mode, where step 4 and step 5 also rewrite the
files, so the change survives a restart.

## Functional requirements

### Read-only-filesystem mode

| ID | Requirement |
|---|---|
| FR-EPH-1 | `CONNECTOR_NODE_STATELESS=1` starts the Node without creating any directory or file. |
| FR-EPH-2 | Unset or `0` leaves today's behaviour unchanged, including the directory creation and both file writes. |
| FR-EPH-3 | Any value other than `1`, `0` or empty fails startup with a message naming the accepted values, following the `PACKAGE_ALLOW_FILESYSTEM_ROOT` precedent. |
| FR-EPH-4 | A missing Server URL, `tunnel_token`, policy, node id or credential fails startup, naming the missing piece. A Node that starts and refuses everything is indistinguishable from a working Node, so a missing piece is a refusal rather than a degraded start. |
| FR-EPH-5 | The identity and the credentials are held in memory only, and no code path attempts a write. |
| FR-EPH-6 | The startup summary prints as it does today, including the `CONNECTOR_CLI_*` block, and additionally names the mode. |
| FR-EPH-7 | The secret is printed in full only when stdout is a terminal, unchanged from today. |
| FR-EPH-8 | Scope validation, the path fence and the permission model are unchanged. Every scope path rule still applies. |
| FR-EPH-9 | The executable deny entry still applies when the build carries a `tunnel_token`, because the binary is still a credential. |
| FR-EPH-10 | The mode is reported in the startup summary and in the console's `show config`, so an operator can tell which mode a Node is in. |
| FR-EPH-11 | `id`, `regenerate` and the `credential` subcommands keep their file-based behaviour and are not silently redirected to memory. In this mode they refuse with a message that names the console. |
| FR-EPH-12 | The config directory is not created, so the deny entries for the identity file, the credential file and the config directory are absent rather than wrong. The deny list already skips an empty path, and the config-overlap check already treats an empty config directory as "this caller has none". |

FR-EPH-11 is the one that needs a decision recorded. Those subcommands operate on
files, and in this mode there are no files. Refusing them with a message that
names the console is the fail-closed choice and is the recommendation; letting
them write to a temporary directory would create files in a mode whose whole
purpose is to create none.

### Configuration sources and precedence

A stateless Node has no config directory, so every value it uses must arrive from
outside the process or from the binary itself. The requirement is that the four
sources compose in a stated order rather than in whichever order the resolvers
happen to run.

| ID | Requirement |
|---|---|
| FR-CFG-1 | The Node reads configuration from four sources: a command-line argument (`--set KEY=VALUE`), an environment variable, a dotenv file (`--env-file <path>` or `CONNECTOR_NODE_ENV_FILE`), and a value compiled into the binary. |
| FR-CFG-2 | The order is argument, then environment, then file, then compiled in. The argument ranks first because it is typed for this one launch; an environment variable is ambient and inherited by every process the shell starts; a file is a default for this installation; the compiled value is the fallback that makes a self-contained build work with no configuration at all. |
| FR-CFG-3 | An empty value counts as unset at every layer, so an exported but empty variable does not shadow a file that holds a value. |
| FR-CFG-4 | A node id or a credential that none of the four sources supplies is generated in memory. This is not a fifth source: it is what a stateless Node does when it has nothing to read. |
| FR-CFG-5 | `--env-file` and `CONNECTOR_NODE_ENV_FILE` must name an absolute path. A relative path is refused, following the rule the six existing path variables already hold. |
| FR-CFG-6 | There is deliberately no default env-file location. The CLI looks beside its executable because a caller runs it from anywhere; a Node is started by a service manager, and a file that appeared in the working directory would silently change what an existing deployment serves. |
| FR-CFG-7 | A file the operator named that does not exist is an error. `envfile.Load` treats a missing file as an empty map, which is right for a default location and wrong here: a typo would fall through to the compiled-in values and the operator would believe a configuration is in force that was never read. |
| FR-CFG-8 | A `--set` value is never printed. A usage error names the key and not the value, because a `--set` argument may carry a `tunnel_token` and an error message is the one place a secret must not reach. |
| FR-CFG-9 | The `--set` pairs are validated before the flag package parses them, because the package echoes a rejected value verbatim as `invalid value "<the whole argument>" for flag -set`. |
| FR-CFG-10 | The policy is the one value that cannot be generated. A build with no embedded policy and no `CONNECTOR_NODE_POLICY_FILE` refuses to start, because a Node that invented its own scopes would be a Node whose operator believes it serves something it does not. |
| FR-CFG-11 | The precedence is decided in one function, so it can be stated rather than inferred from whichever resolver ran first. |

FR-CFG-9 records a defect that was measured rather than anticipated. The first
implementation validated a `--set` pair inside `overrideFlag.Set`, and
`overrideFlag.String()` printed keys only. Running
`connector-node run --set 'BAD-KEY=super-secret-value'` still printed the secret,
because the flag package wraps a `Set` failure as
`invalid value "<the whole argument>" for flag -set` and never calls `String()` on
that path. The fix is a pre-pass over the arguments before `flags.Parse`.

FR-CFG-10 is the asymmetry that makes the mode honest. Every other value has a
sensible generated form: a node id is random, a credential is random, a Server URL
has no safe default but a missing one is a startup failure. A policy has no
generated form at all, because a policy is a statement about what the operator
intends to expose, and nothing in the process can know that.

### In-process console

| ID | Requirement |
|---|---|
| FR-CON-1 | `CONNECTOR_NODE_CONSOLE=1` starts the console alongside the dialer, without blocking it. |
| FR-CON-2 | Every command operates on in-memory state and writes no file. |
| FR-CON-3 | `show credentials` prints key identifiers only, never a secret. |
| FR-CON-4 | A mutating command prints a generated secret once, and only when stdout is a terminal. |
| FR-CON-5 | `regenerate id` takes effect without a restart, dropping the channel authenticated under the retired identity. |
| FR-CON-6 | The console and the dialer share one identity holder, so a regeneration cannot be observed half-applied. |
| FR-CON-7 | The last credential cannot be removed, with the same message the file-based command uses. |
| FR-CON-8 | Input is never written to a history file, because the mode may be on a read-only filesystem and because a history file would record a secret. |
| FR-CON-9 | An unknown command prints the command list and does not stop the Node. |
| FR-CON-10 | The console works in both modes: with files present, a mutation also updates the files; without files, it updates memory only. |
| FR-CON-11 | `quit` closes the channel before exiting, so a caller mid-request is answered rather than cut off. |
| FR-CON-12 | The console is documented in `--help` and in the Node skill, because a reader of the skill cannot see the source. |
| FR-CON-13 | Enabling the console with stdout redirected fails startup rather than starting a console that silently reads nothing. |
| FR-CON-14 | A credential rotation under an existing key id is applied even though the public key identifiers are unchanged. The holder's current comparison reports "unchanged" for that case, so the console must not rely on it alone. |
| FR-CON-15 | The console can silence the process logger with `log off` and restore it with `log info`, because the console and the log share one terminal and a log record written mid-line makes the operator believe they typed it. The switch changes the process logger, not only the console's own output, so the retry warnings stop too. |
| FR-CON-16 | The log level is not persisted across a restart, because a Node that stayed silent after a restart would hide the reason it cannot connect. A silenced Node still reports a fatal error on the way out. |
| FR-CON-17 | A command that names a subject or an action it does not have says which one was wrong and what the valid ones are, rather than repeating a usage line. `credential list` points at `show credentials`; `regenerate bogus` names `bogus`. |
| FR-CON-18 | `quit` and end-of-input print that the console closed and the Node keeps running, because a silent exit reads as a hang. |
| FR-CON-19 | `show config` prints one field per line, so a value is never split across a wrap boundary. |

FR-CON-14 records a measured constraint rather than a preference.
`IdentityHolder.ReplaceCredentials` compares the public key identifiers, because a
credential set deliberately exposes no way to read a secret back. Two sets with
the same identifiers but different secrets are therefore reported as unchanged,
which is the correct answer for the file watcher and the wrong answer for a
console command whose whole purpose is to rotate a secret under one identifier.

### Console command surface

Read-only commands print information and change nothing:

| Command | Prints |
|---|---|
| `show config` | Server address, config source (embedded or file), mode, policy source |
| `show identity` | The node id, and whether it came from the binary or was regenerated in this process |
| `show credentials` | The key identifiers only, never a secret |
| `show scopes` | Each scope name, its path, its grant, and whether the directory is absent |
| `show status` | Whether the channel is connected, the generation, and the selected file transport |
| `help` | The command list |

Mutating commands change state and write no file in this mode:

| Command | Effect |
|---|---|
| `regenerate id` | Replaces the node id, drops the channel, reconnects under the new id |
| `credential add --key-id NAME` | Adds a credential and prints the secret once |
| `credential rotate --key-id NAME` | Replaces one credential's secret and prints the new value once |
| `credential remove --key-id NAME` | Removes a credential; the last one cannot be removed |
| `quit` | Stops the Node, closing the channel |

## Non-functional requirements

- The mode adds no new dependency and no new environment read inside business
  logic. Both switches are read once at the process boundary and passed down as
  fields on `Config`, following the existing rule that a function below the
  boundary never reads the environment.
- The mode adds no file read on the common path. It removes two writes and one
  `MkdirAll`; startup cost therefore falls rather than rises.
- The console is a goroutine reading stdin, so it cannot block the dialer. A
  console that blocked the dialer would make an interactive convenience into an
  availability defect.
- The console's output goes to stdout and its diagnostics to stderr, matching the
  existing split between the startup summary and the log.
- The console holds no secret in a variable that outlives the command that
  printed it, following the existing rule that a runtime does not keep a
  generated credential.
- The change is cross-platform. The console reads stdin, which exists on Linux,
  macOS and Windows; no terminal-specific API is used.
- The mode is fail-closed: every precondition is checked before the Node
  advertises anything, so a misconfigured Node never appears online.

## Functional dependencies

| Dependency | Why it matters |
|---|---|
| `internal/node/config.go` (`resolveConfigDir`) | The unconditional `os.MkdirAll` is the first write the mode must skip |
| `internal/node/identity_store.go` (`EnsureIdentityWithSeed`) | The unconditional `SaveIdentity` is the second write |
| `internal/node/credentials_store.go` (`EnsureCredentialsWithSeed`) | The unconditional `SaveCredentials` is the third write |
| `internal/node/run.go` (`Open`) | Assembles identity, credentials, deny list and authority in one place; the mode is decided here |
| `internal/node/identity_holder.go` | Already exposes atomic `ReplaceNodeID` and `ReplaceCredentials`; the console must reuse them rather than add a second source of truth |
| `internal/node/identity_watch.go` | The file-polling adoption path; the console needs an in-memory path that does not depend on a file |
| `internal/node/dialer.go` | Already treats an empty `ConfigDir` as "no file to watch", and owns the change channel that drops a channel on an identity change |
| `internal/node/fence.go` | Already skips empty deny paths and already treats an empty config directory as "this caller has none" |
| `internal/node/embedded` | Supplies the compiled Server URL, tunnel token, policy, node id and credential |
| `internal/nodehelp/nodehelp.go` | The only place an operator learns the two switches exist |
| `skills/connector-node-setup` | The only documentation a recipient reads |

## MoSCoW priority

| Priority | Item |
|---|---|
| Must | FR-EPH-1, 2, 3, 4, 5, 6, 8, 9, 11; FR-CON-1, 2, 3, 5, 6, 7, 9, 10, 12 |
| Should | FR-EPH-7, 10, 12; FR-CON-4, 8, 11, 13, 14, 15, 16, 17, 18, 19 |
| Could | A `show policy` command that prints the effective policy document; a `show channel` command that prints the last handshake result |
| Won't (this release) | Changing the tunnel token or the policy from the console; a console over a network socket; a console that survives a restart in stateless mode |

## Release recommendation

Ship the two features as separate logical units in one release, each behind its
own opt-in and each off by default.

The read-only mode is the smaller change and the one with an external deadline:
a machine with an immutable root cannot run the Node at all today. The console is
the larger change and depends on the mode being in place, because the console is
what makes a memory-only Node recoverable.

Shipping them separately matters for review: a failure in one must not obscure
the other, and the mode's acceptance criteria are about writes that must not
happen, while the console's are about state that must change.

## Acceptance criteria

### Read-only-filesystem mode

- **AC-EPH-1** On a filesystem the process cannot write to, the Node starts,
  connects and serves `file.read`, `file.list` and `file.stat`.
- **AC-EPH-2** After a full session, no file and no directory was created
  anywhere under the configured path, and the path itself was never created.
- **AC-EPH-3** With the variable unset, the existing test suite passes unchanged.
- **AC-EPH-4** With the variable set to `true`, startup fails and the message
  names `1`, `0` and empty.
- **AC-EPH-5** With the policy absent, startup fails naming the policy, and the
  process does not connect.
- **AC-EPH-6** The startup summary in this mode names the mode and prints the
  same `CONNECTOR_CLI_*` block.
- **AC-EPH-7** A scope that escapes is still refused with `denied`, and a
  malformed path is still `invalid_argument`.
- **AC-EPH-8** A build carrying a `tunnel_token` still denies its own executable
  in this mode.
- **AC-EPH-9** `regenerate` in this mode refuses with a message naming the
  console, rather than creating a file.

### Configuration sources and precedence

- **AC-CFG-1** With every `CONNECTOR_NODE_*` variable unset and only
  `--env-file` supplied, the Node starts and connects using the values in that
  file.
- **AC-CFG-2** A `--set` value overrides the same key in the env file, and the
  startup summary shows the argument's value.
- **AC-CFG-3** An environment variable overrides the same key in the env file,
  and the startup summary shows the variable's value.
- **AC-CFG-4** An exported but empty variable does not shadow a value in the env
  file.
- **AC-CFG-5** `--env-file` naming a relative path fails startup with a message
  that says the path is relative and why that is refused.
- **AC-CFG-6** `--env-file` naming a file that does not exist fails startup with
  a message that names the path.
- **AC-CFG-7** `--set` with no `=` fails with a message naming the pair and
  stating the `KEY=VALUE` form.
- **AC-CFG-8** `--set` with an invalid key fails with a message that names the
  key and does not contain the value, verified by searching the output for the
  known value.
- **AC-CFG-9** A build with no embedded policy and no `CONNECTOR_NODE_POLICY_FILE`
  fails startup naming the policy.
- **AC-CFG-10** With the variable unset and no flag, the existing test suite
  passes unchanged, so the feature is additive.

### In-process console

- **AC-CON-1** `show identity` prints the same node id the startup summary
  printed.
- **AC-CON-2** `show credentials` output contains no secret, verified by
  searching the output for the known secret.
- **AC-CON-3** `regenerate id` changes the id, the old id returns `node_offline`,
  and the same credential still works under the new id.
- **AC-CON-4** `credential remove` on the last credential is refused with the
  existing message.
- **AC-CON-5** After a console session in read-only mode, no file was created.
- **AC-CON-6** After a console session in file mode, the change survives a
  restart.
- **AC-CON-7** `quit` exits with status 0 and leaves no orphan process.
- **AC-CON-8** An unknown command does not stop the Node.
- **AC-CON-9** `credential rotate` under an existing key id changes the secret
  that authenticates, and the old secret is refused.
- **AC-CON-10** `log off` stops the retry warning from appearing on the terminal
  for at least two retry intervals, and `log info` makes it appear again. Verified
  by reading the recorded terminal output, not by reading the level variable.
- **AC-CON-11** `log silent` is refused, names the unknown word, and leaves the
  level unchanged.
- **AC-CON-12** `quit` prints `console closed; the node keeps running` and the
  process is still alive afterwards.
- **AC-CON-13** `credential list` names `show credentials`, and `regenerate bogus`
  names `bogus`.
- **AC-CON-14** Every line of `show config` is a single field and no line exceeds
  80 characters.

## Assumptions and constraints

- **The compiled configuration is a seed, not an authority, in file mode.** That
  remains true and is unchanged. In read-only mode there is no file, so the
  compiled value is the only value; the seed becomes the authority by necessity
  rather than by a change of rule.
- **A Node with no credential accepts nothing.** The mode therefore requires at
  least one credential to be present, and refuses to start without one. The
  alternative, starting and refusing every caller, is the failure mode the
  existing design already refuses for a missing policy file.
- **The mode removes two recorded residual risks and no others.** A copy of the
  config directory cannot be served because there is no config directory, and
  the Windows mode gap on `credentials.yaml` does not apply because there is no
  `credentials.yaml`. The binary-copy leak and the tunnel-token impersonation
  risk are unaffected, because both concern the compiled tunnel token, which this
  mode still requires.
- **The console is not a remote interface.** It reads the process's own stdin. A
  console reachable over a socket would be a second authentication surface, and
  the design has exactly three gates that it does not want to widen.
- **A memory-only Node loses its state on restart.** A regenerated address and a
  revoked credential are gone when the process exits. This is stated in the
  startup summary and in the skill rather than prevented, because preventing it
  would require writing a file, which is the thing the mode exists to avoid.
- **The console must not become a second source of truth.** It mutates through
  the same identity holder the dispatcher and the dialer already share, so a
  change is observed by both components at the same moment.

## Open questions

- Should `credential rotate` exist as its own command, or should
  `credential add --key-id NAME` replace an existing identifier? A separate
  command states the intent, and an `add` that silently replaced a secret would
  be a revocation the operator did not ask for.
- Should the console print the full policy document on `show scopes`, or only the
  scope names, paths and grants? The document may name paths the operator already
  knows, but printing it in full makes the console output long enough to scroll a
  terminal.
- Should the read-only mode also be expressible as a packaging-time decision, so
  a bundle can be built that always runs this way? A packaging-time decision
  cannot be widened by whoever runs the artifact, which is the argument the
  `allow_filesystem_root` file already makes.
- Should `quit` wait for in-flight requests to finish, or close immediately? A
  wait needs a bound, and a bound is a number nobody has measured.

## Recommended product decisions

- Keep both switches as environment variables rather than flags. The mode changes
  what the process may write, and the rest of the Node's configuration is already
  environment-based; a flag would be a second spelling for one concept.
- Refuse `regenerate` and the `credential` subcommands in read-only mode with a
  message naming the console. A refusal is visible; a silent redirect to memory
  would make the same command mean two different things depending on a variable.
- Add `credential rotate` as a separate command rather than overloading `add`.
- Make the console's mutations go through the identity holder, and give the
  holder a way to apply a rotation under an unchanged key id, because the current
  comparison cannot see it.
- Ship the mode first and the console second, as two logical units, each with its
  own commit and its own verification evidence.
