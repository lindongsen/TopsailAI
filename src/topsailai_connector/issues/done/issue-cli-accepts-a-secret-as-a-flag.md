---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-13
updated: 2026-11-13
---

# The CLI accepts a secret as a flag, which TC-CLI-9 says it must not

## Symptom

`docs/cases/TestCase_cli-and-routing.md` TC-CLI-9 stated that the CLI must not
accept a secret as a flag value, because the value would be recorded in the shell
history and the process table. The implementation does accept it:

```
connector-server cli --client-token gamma --node node_a.b --scope project file.list
```

`parseArguments` registers `--client-token` and `--node`, and both are documented
as supported flags in `docs/API.md` and `skills/connector-client/SKILL.md`.

## Why this was not a typo

The two sides disagreed about a security property, not about spelling:

- The test case treated a secret on the command line as a leak, because `argv` is
  visible in the process table to every user on the host and is written to shell
  history by default.
- The implementation and two documents treated the flag as a convenience, with the
  environment variable as the recommended form.

## Decision

**Option 2: keep the flags and change the test case.** Decided by the human on
2026-11-13.

The flags `--client-token` and `--node` stay. A secret passed on the command line
is now a documented, accepted trade-off rather than an undocumented contradiction.
The environment variable remains the recommended form, because it keeps the secret
out of `argv` and out of shell history.

## Why this option

- The flag is what makes the CLI usable from a script that already holds the
  secret in a variable, and from a one-off invocation where exporting an
  environment variable is more work than the request itself.
- The exposure is real but bounded: `argv` is readable by other users on the same
  host, and shell history is written to disk. Both are local exposures, and a
  local account that can read `argv` can usually also read the environment of the
  same process through the same privilege.
- Removing the flag would not remove the exposure, because the environment
  variable is equally readable from `/proc/<pid>/environ` on Linux by the same
  accounts that can read `argv`. Option 1 would have traded a documented
  convenience for an undocumented equivalent risk.
- A warning on stderr (option 3) was rejected because it fires on every scripted
  invocation, which trains the operator to ignore it. A warning that is always
  present is not a warning.

## What changed

- `docs/cases/TestCase_cli-and-routing.md` TC-CLI-9 now asserts the accepted
  behaviour: the flag exists, it is honoured, and a flag value takes precedence
  over the environment variable when both are present. The precedence was
  verified by execution, not by reading: `parseArguments` resolves each value with
  `firstNonEmpty(*flag, lookup(env))`, and a probe passing both forms returned the
  flag value for `--server`, `--client-token` and `--node`.
- `docs/permission-design.md` residual risks gained a row naming the flag as an
  accepted exposure with the environment variable as the mitigation.
- `docs/API.md` and `skills/connector-client/SKILL.md` state that the environment
  variable is preferred and why.

## Related

- `issues/done/issue-cli-example-contradicts-argument-order.md` fixed the same
  document's command shape but did not examine this case.
- `docs/permission-design.md` residual risks: "Secret in a shell history or log".
