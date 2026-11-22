---
maintainer: AI
author: DawsonLin
status: fixed
---

# Interactive and non-interactive command surfaces are not fully aligned

## Requirement being checked

The non-interactive surface must cover every interactive command. It may offer more, never less.

## Verified state

Both surfaces were read from source, not from documentation:

- Interactive dispatch: `internal/tui/interactive.go:582-712`, scope matrix
  `internal/tui/scope_commands.go:29-70`, help catalog `internal/tui/help.go:74-100`.
- Standalone dispatch: `src/main/agent-cluster-cli/main.go:322-455`, advertised order
  `internal/tui/help.go:283`.

Interactive canonical commands (25): `list`, `cd`, `show`, `info`, `start`, `resume`, `stop`,
`clean`, `btw`, `interrupt`, `ctl`, `drive`, `logs`, `project`, `history`, `messages`, `model`,
`send`, `endpoints`, `status`, `refresh`, `watch`, `help`, `quit`, `exit`.

Standalone advertised commands (23): `list`, `refresh`, `project`, `history`, `messages`, `model`,
`endpoints`, `show`, `info`, `logs`, `status`, `send`, `btw`, `interrupt`, `ctl`, `exec`, `start`,
`resume`, `stop`, `clean`, `drive`, `help`, `interactive`.

## Gaps where an interactive capability has no standalone path

### 1. `agent.model.registry` and `agent.model.set` are interactive-only — FIXED

Standalone `model` accepted only `<endpoint> <session> [profile]`
(`src/main/agent-cluster-cli/main.go:380-387`), which reaches the session catalog read and the
session-scoped select. The machine-wide registry read and the machine-wide launch-default
declaration existed only in `internal/tui/interactive_model_registry.go` and
`internal/tui/interactive_model_set.go`.

Evidence at the time: `GetModelRegistry` had no caller outside `internal/tui`, and
`OperationAgentModelSet` was constructed only at `internal/tui/interactive_model_set.go:237`.

Impact: a script could not read which model a launch from an Endpoint would use, and could not
declare one. Both are standard operations with their own capability entries, so the capability was
advertised but unreachable non-interactively. This is the exact defect the project's own
"non-interactive first" rule forbids.

Resolution: the standalone surface now dispatches `model registry <endpoint>` and
`model set <endpoint> <profile>` (`src/main/agent-cluster-cli/model_registry_cli.go`). Both reuse the
interactive helpers rather than reimplementing them: `tui.GetModelRegistry`,
`tui.ResolveModelRegistrySelector`, `tui.ModelRegistryError`, `tui.ModelRegistryRowLabel`,
`tui.ModelSetPayload` and the shared `submitActionWithProgress` path. `model set` submits a
target-less intent, matching the contract that a machine-wide declaration carries no resource
target. The standalone `model` help entry advertises all three forms, and
`TestModelRegistryAndSetAreAdvertised` fails if the advertisement is removed.

### 2. `resume -s <session_id>` has no standalone spelling — FIXED

Interactive `resume` accepts `-s`/`--session` and forwards `ProviderSessionHandle`
(`internal/tui/interactive_ops.go:1209`). Standalone `resume` built
`CommandTarget{Kind: "session", ResourceID: resourceID}` only, and `ProviderSessionHandle` appeared
nowhere in `src/main/agent-cluster-cli/`.

Impact: a session the Endpoint has never discovered has no cluster resource ID, so it could be
resumed interactively but not from a script. The handle form exists precisely for that case.

Resolution: standalone `resume` now accepts `-s`/`--session` and forwards the handle through
`ActionRequest` into the intent target. The Endpoint already resolved handles
(`internal/endpoint/executor.go:489-523`), so this was a client-side wiring gap and needed no
protocol, Server, Endpoint or Provider change. The two spellings are reconciled after parsing and
rejected when they disagree, mirroring `-c`/`--max-chars`. In the handle form the resource slot does
not exist, so a positional after the endpoint is refused rather than reinterpreted as a generation,
and the generation travels in `--generation`.

Two latent defects were found and fixed in the same unit:

- The documented positional form `resume <endpoint> <resource> <generation>` silently discarded the
  generation, because `resume` was absent from the generation branch and the slot was read as a
  discarded text payload. The Endpoint therefore revalidated nothing while the command reported
  success.
- `PrepareAction` reported only `request.ResourceID` in the confirmation question, so the handle form
  printed `target=` and asked the operator to confirm a mutating command without naming the session.
  The shared layer now names whichever identity the request carries, which fixes both surfaces.

### 3. Endpoint-scope `command.exec` has no standalone spelling — FIXED

Interactive `!` runs in session scope and in endpoint scope; endpoint scope sends a target-less
intent (`internal/tui/interactive_shell.go:220-250`, `requireShellScope`). Standalone `exec`
required `<endpoint> <resource> <generation> -- <argv...>` and refused without a resource
(`src/main/agent-cluster-cli/ctl_exec.go:105-121`). The standalone help stated the asymmetry
explicitly (`internal/tui/help.go`, `exec` entry).

Impact: the machine-scoped form of `command.exec` was unreachable from a script, even though the
Endpoint serves it and the capability is advertised.

Resolution: standalone `exec` now accepts `exec <endpoint> -- <argv...>` and submits a target-less
intent. This was a client-side wiring gap only. `PrepareAction` already returned a target-less intent
for `command.exec` when neither a resource nor a handle was set
(`internal/tui/command_actions.go:93-100`), and the Endpoint already served that shape through
`endpointCommandAdapter` (`internal/endpoint/executor.go:572`) and `targetKey`
(`internal/endpoint/executor.go:675-677`), resolving the working directory from
`AGENT_CLUSTER_ENDPOINT_COMMAND_DIR`. No protocol, Server, Endpoint or Provider change was needed.

The two forms are distinguished by the head length rather than by a flag, because the endpoint is
always the first positional and a session target always names a resource after it, so no input is
ambiguous between them. A generation supplied with the endpoint form is refused rather than ignored,
because the endpoint addresses no process and a silently discarded generation would look like a
revalidation that never happened.

A shared-layer defect was fixed in the same unit: `confirmationTargetLabel` now names the endpoint
when a request carries neither a resource nor a handle, so the endpoint form asks
`target=endpoint=ep` instead of printing an empty `target=`. That label is shared by both surfaces,
so the interactive endpoint-scope `!` confirmation was corrected by the same change.

## Deliberate exceptions, not gaps

- `cd`, `quit`, `exit` navigate state that exists only inside the REPL loop.
- `watch` ticks add no behaviour: each tick is `list` or `refresh`, both reachable standalone. Its
  `--trigger` script is a foreground convenience in the operator's own client process.
- `>`, `!`, `/`, `ctl.<action>`, `logf`, `lf`, `lb` and the one-letter aliases are spellings, not
  capabilities. `exec`, `ctl`, `logs` and `list` carry the same behaviour standalone.

## Documentation defect found while checking

The audit table in `docs/cli-command-surface-rules.md:347-372` has no row for `model`
(`agent.model.registry`, `agent.model.set`) or `project` (`project.add`, `project.remove`). Both
families are implemented and advertised, so the table that claims to record "the verified state of
every command" is stale for the two newest families. A stale audit table is worse than a missing
one, because it reads as a complete verification.

## Suggested order of repair

1. Add a standalone `model registry <endpoint>` read and `model set <endpoint> <profile>` mutation,
   reusing the existing runner methods so the two surfaces cannot diverge.
2. Add `-s`/`--session` to standalone `resume`, forwarding `ProviderSessionHandle`.
3. Allow standalone `exec` to omit the resource and generation, producing a target-less intent,
   gated on the same "exactly one capable adapter" rule the Endpoint already applies.
4. Add the missing audit rows and a structural test that every interactive canonical command is
   either dispatched standalone or listed in one explicit exception set.

## Status

Gap 1 fixed and verified. Gap 2 fixed and verified. Gap 3 fixed and verified.

Gap 3 evidence: `make test-unit-cli` green (`internal/client`, `internal/tui`,
`src/main/agent-cluster-cli`), `go build ./...` clean, `go vet` clean. The new tests were proven to
fail when each guard was deliberately broken: making the endpoint form carry a resource failed the
target-less assertion with `target = &{Kind:session ResourceID:invented ...}, want nil`, removing the
generation refusal failed with `error = <nil>, want a refusal that names the generation`, dropping the
endpoint from `confirmationTargetLabel` failed with `confirmation required for exec target=`, and
removing the endpoint form from the help syntax failed the advertisement test. The real binary was
driven end to end: `exec ep -- ls` prints `confirmation required for exec target=endpoint=ep`,
`exec ep --generation gen-1 -- ls` is refused, `exec ep res_abc -- ls` still requires a generation, and
`exec -- ls` reports the two-form usage.

Gap 2 evidence: `make test-unit-cli` green (`internal/client`, `internal/tui`,
`src/main/agent-cluster-cli`), `go build ./...` clean, `go vet` clean. The new tests were proven to
fail when each guard was deliberately broken: removing the dash check in `hoistTrailingFlags` failed
the bare-word cases, removing `resume` from the generation branch failed the positional-generation
case, dropping the handle from `ActionRequest` failed the handle-forwarding case, and reverting the
confirmation label failed the handle-target case. The real binary was also driven end to end:
`resume ep -s sad-1` hoists the trailing flag and prints `target=session=sad-1`, while
`-s sad-1 --session sad-2` and `resume ep res_abc -s sad-1` are both refused.

A latent hoisting defect was found and fixed in the same unit: `hoistTrailingFlags` consulted
`globalOptionNames` for every argument, and `version.SplitOptionName` trims leading dashes, so a bare
positional word matching an option name was hoisted in front of the subcommand. `messages ep session`
therefore failed with `unknown command "session"`. Every option name that can also be a positional
value had this defect, not only the newly added `session`.

Gap 1 evidence: `go build ./...` clean, `go vet` clean, `go test ./internal/tui/
./src/main/agent-cluster-cli/` green, and the new tests were proven to fail when each dispatch branch
and the help advertisement were deliberately removed.
