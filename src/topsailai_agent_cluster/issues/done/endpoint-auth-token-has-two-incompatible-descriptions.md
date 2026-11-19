---
maintainer: AI
author: DawsonLin
status: resolved
created: 2026-11-20
resolved: 2026-11-20
resolution: removed the key and required an explicit CLI credential
---

# The Endpoint `AUTH_TOKEN` has two incompatible descriptions and one unusable form

## Resolution

The key was removed rather than repaired. Commit `130b1af2` deletes `AUTH_TOKEN` from the endpoint
configuration template and from every installer path, and `agent-cluster-node-setup` now takes the
credential explicitly with `--token <key_id.secret>`.

The reason removal was chosen over correcting the value: the Endpoint daemon never reads the key, so
the only thing it could ever do was feed the CLI env writer, and it fed it a bare secret that the CLI
rejects in hmac mode. A key that exists solely to produce an unusable credential is not worth keeping
in a configuration contract. The credential now lives in exactly one place, the CLI env file, and
writing it is an explicit operator act.

Behaviour change, stated plainly: a fresh node no longer gets a CLI env file from the installer. Both
installers warn and name the command that writes it. This is deliberate, because the previous
behaviour wrote a file that could not authenticate.


## What was claimed, and why it was wrong

While mapping the credential sites for the 2.0.0 rotation, the Endpoint `AUTH_TOKEN` was reported as
"dead configuration". The human rejected that: "endpoint的auth_token应该不是死配置，你仔细读代码".

The human is right. The evidence for the wrong claim was real but answered a different question:

- `cfg.AuthToken` is consumed only by `src/main/agent-cluster-server/main.go:188`.
- The Endpoint branch of `scripts/agent-clusterctl` (line 375 onward) never passes `--auth-token`.
- `src/main/agent-cluster-endpoint/main.go` contains zero references to `AuthToken`.

All three are true, and all three describe the **daemon**. The key is consumed by the **installer**:

| Consumer | Site | Effect |
|---|---|---|
| Debian package postinst | `scripts/deb/postinst.endpoint:37` | Sources `node.conf`, passes `AUTH_TOKEN` to `cli_env_write` |
| Bundle installer | `scripts/install-node.sh:161` | Same call for a copied bundle |

`cli_env_write` (`scripts/lib/cli-env.sh`) writes `AGENT_CLUSTER_CLI_SERVER_TOKEN` into the per-user
CLI env file, and the CLI reads that key at `src/main/agent-cluster-cli/cli_environment.go:9`. So
`AUTH_TOKEN` is the install-time source of the operator CLI's Server credential on that node.

## The two incompatible descriptions

The shipped template and the installer disagree about what the value is:

| Source | Says the value is |
|---|---|
| `conf/node.endpoint.conf.example:22-25` | "Pre-provisioned credential the operator CLI presents **to this Endpoint**... The Endpoint verifies it independently of the Server, so this value is **not the Server credential**" |
| `scripts/deb/postinst.endpoint:37` | The **Server** credential, written into `AGENT_CLUSTER_CLI_SERVER_TOKEN` |

Both cannot be true. The template describes an endpoint-token; the installer treats it as a
server-token. The daemon reads neither, so nothing fails at runtime and the disagreement is invisible.

## The form is unusable in the documented mode

`conf/node.endpoint.conf.example:22-23` states that in `hmac` mode the value "must be exactly one
`key_id.secret` pair". The value in force on every node is a bare 48-hex secret:

```text
topsail node.conf AUTH_TOKEN = 2d253501063fa587606214d5b21dfaf4ea666bdafe4dfad1
gd-dev endpoint node.conf    = 2d253501063fa5876062...
```

It matches none of the five `key_id.secret` pairs. `internal/client/api.go:85` refuses exactly this
form in HMAC mode:

```text
server credential is not in key_id.secret form required by hmac mode
```

So a credential written by the installer from this value cannot authenticate in the mode every node
runs. The defect is currently masked on all four nodes because the CLI env file already exists in the
profile form (`AGENT_CLUSTER_CLI_SERVER_PROFILES` / `SERVER_PROFILE_TOKENS`), so `cli_env_write`
refuses to overwrite it and prints:

```text
ERROR: /root/.topsailai/.topsailai_agent_cluster.env already exists with different content; re-run with --force to replace it
```

That refusal is the only reason the unusable value never reached the CLI. A fresh node installed with
`--force`, or a node whose env file is removed, would receive a credential that fails every request.

## Why this is pre-existing, not introduced by the rotation

The value before the rotation was also a bare 48-hex secret
(`551ae42762032de30ccad72d792c804543409697ba0f29ee`, from
`.tmp/acops/backup-20261120T010938/topsail/node.conf`). The rotation preserved the form and changed
only the secret, so it neither created nor fixed this defect.

## What the rotation did

The Endpoint `AUTH_TOKEN` was rotated to a new bare 48-hex secret on all four nodes, because the
instruction was to regenerate every key and secret. The value is in force and verified:

```text
live = 2d253501063f...   new = 2d253501063f...   MATCH
```

Rotating it is correct regardless of the defect: the key is a real credential source, and leaving a
known value in place would defeat the rotation.

## Decision needed

Three outcomes are possible and the choice belongs to the human:

1. **Make it the endpoint-token the template describes.** Then the Endpoint daemon must read it, the
   launcher must pass it, and the installer must stop writing it as a Server credential. This is the
   larger change and it duplicates the policy directory, which already decides caller authority.
2. **Make it the Server credential the installer assumes.** Then the value must be a `key_id.secret`
   pair, the template comment must say so, and the daemon keeps ignoring it. This is the smaller
   change and it makes the installer's behaviour correct.
3. **Remove it.** The policy directory already carries the Endpoint's caller authority, and the CLI
   env file is written by the operator with the profile form. The key would then have no consumer and
   the installer would need a different source for the CLI credential.

Option 2 is the smallest correct change and it matches what the installer already does. It is not
implemented here because it changes a shipped configuration contract and needs the human's decision.

## Related

- `LEARN.md`, "A configuration key can be dead for the daemon and live for the installer".
- `.task/plan_20261120T010646_rebuild-repackage-rotate-credentials.md`, "Credential map before the
  change", which now records both consumers.
