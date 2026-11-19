---
maintainer: AI
author: DawsonLin
---

# connector-node-setup: executed evidence for `scope list`

Every claim the skill makes about `scope list` was executed against the built
binary, not read off the source. The binary under test is `bin/connector-node`
built by `make build` from commit `648eef5b`.

## Environment

| Item | Value |
|---|---|
| Host | Linux, Go 1.25.12 |
| Binary | `bin/connector-node` |
| Live Node | started in tmux session `skillverify`, policy with two scopes |
| Live policy | `project` -> `.tmp/e2e/scope` with `[read, list, stat]`; `readonly` -> `.tmp/e2e/scope2` with `[read]` |

## Claim: the command prints the scope names, one per line, sorted

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/e2e/node-config connector-node scope list
```

Expected: `project` then `readonly`, one per line, sorted, nothing else.
Actual:

```
project
readonly
```

Status: PASS. Exit status 0.

## Claim: it prints names, never paths

Command:

```
connector-node scope list | grep -c '/TopsailAI'
```

Expected: 0, because a path is the machine's filesystem layout and does not help
anyone fill `--scope`.
Actual: `0`.

Status: PASS.

## Claim: it works before the first start and where a scope directory does not exist

This is the load-bearing claim, because it is the reason the command does not open
scopes. A fresh config directory was created holding only a policy whose scope path
does not exist, and no `identity` file.

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/skilltest/fresh connector-node scope list
```

Expected: `notyet`, exit 0, even though `.tmp/skilltest/does-not-exist` was never
created and no identity file existed.
Actual: `notyet`, exit 0. The config directory contained only `policy.yaml`.

Status: PASS. This is the case a fence-opening implementation would have failed.

## Claim: an empty policy prints nothing and exits 0

Command:

```
CONNECTOR_NODE_POLICY_FILE=.tmp/skilltest/fresh/empty.yaml connector-node scope list
```

Expected: no output, exit 0, because an empty policy is a valid document that
refuses every request rather than an error.
Actual: no output, exit 0.

Status: PASS.

## Claim: a missing policy exits 1 and names the path

Command:

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/skilltest/nonexistent connector-node scope list
```

Expected: exit 1 with a message naming the missing file.
Actual: exit 1, `connector-node: policy file is missing: /TopsailAI/src/topsailai_connector/.tmp/skilltest/nonexistent/policy.yaml`.

Status: PASS.

## Claim: a malformed policy exits 1 and reports the same reason `run` reports

Command:

```
CONNECTOR_NODE_POLICY_FILE=.tmp/skilltest/fresh/bad.yaml connector-node scope list
```

Expected: exit 1, naming the relative scope path.
Actual: exit 1, `connector-node: scope "bad": path "rel/path" is relative; a relative path resolves differently per launch`.

The same policy through `run`:

```
CONNECTOR_NODE_TUNNEL_TOKEN=0123456789abcdef0123456789abcdef connector-node run
```

Actual: exit 1, `connector-node: load authority: scope "bad": path "rel/path" is relative; a relative path resolves differently per launch`.

Status: PASS after a wording correction. The reason is identical but the prefix
differs (`load authority: `), and the skill originally claimed "the message the Node
would print", which is not literally true. The skill now states the difference and
quotes both forms, because a documented message must be the string the program
emits.

## Claim: exit status 2 for a rejected command line

| Command | Expected | Actual | Status |
|---|---|---|---|
| `connector-node scope` | 2, `usage: scope needs a subcommand: list` | 2, same | PASS |
| `connector-node scope lst` | 2, `usage: unknown scope subcommand "lst"; want list` | 2, same | PASS |
| `connector-node scope list project` | 2, `usage: unexpected argument "project"; want flags only` | 2, same | PASS |

## Claim: a relative CONFIG_DIR is refused

Command:

```
CONNECTOR_NODE_CONFIG_DIR=relative/dir connector-node scope list
```

Expected: exit 1, because a relative path resolves differently per launch.
Actual: exit 1, `connector-node: CONNECTOR_NODE_CONFIG_DIR "relative/dir" is relative; a relative path resolves differently per launch`.

Status: PASS.

## Claim: an embedded build lists the scopes it carries and refuses a policy file

Built with `-ldflags "-X .../embedded.PolicyBase64=<base64> -X .../embedded.ServerURL=..."`.

| Command | Expected | Actual | Status |
|---|---|---|---|
| `scope list` on the embedded build | the two embedded names, exit 0 | `embeddedone`, `embeddedtwo`, exit 0 | PASS |
| `scope list` with `CONNECTOR_NODE_POLICY_FILE` set | exit 1, refusing the second source | exit 1, `CONNECTOR_NODE_POLICY_FILE is set but this build compiled its policy in; ...` | PASS |

## Claim: the help page documents the command

Command:

```
connector-node help scope
```

Expected: NAME, SYNOPSIS, DESCRIPTION, SUBCOMMANDS, ENVIRONMENT, EXIT STATUS and
EXAMPLES sections, and the main SYNOPSIS listing `scope list`.
Actual: all seven sections present; the DESCRIPTION states why a caller cannot ask
the Node and why names are printed rather than paths.

Status: PASS.

## Limitations

- The Windows behaviour of `scope list` was not executed on this host. The command
  reads a YAML document and prints strings, so it has no platform-specific path
  logic, but that is an argument rather than a measurement.
- The embedded-build cases were run against a throwaway binary built for this
  check, not against a shipped artifact.

## Claim: the startup summary prints on every start, with the secret in full on a terminal

Skill version under test: 1.2.0.

The claim has two halves, and each was measured separately because a test that
only exercised the terminal form would leave the protective branch unmeasured.

### First start, stdout is a terminal

Command, run inside a tmux session so stdout is a real pty:

```
CONNECTOR_NODE_CONFIG_DIR=<config> \
CONNECTOR_NODE_POLICY_FILE=<config>/policy.yaml \
CONNECTOR_NODE_SERVER_URL=ws://127.0.0.1:59999/channel \
CONNECTOR_NODE_TUNNEL_TOKEN=termtest-tunnel-token \
  connector-node run
```

The config directory held only `policy.yaml`, so this was a genuine first start.

Actual output, captured from the pane:

```
a new node id was generated by this start
a new credential was generated by this start
=== connector-node ===
server        : ws://127.0.0.1:59999/channel
node id       : node_4jlc54vvhsks2ymt2zw2sys724
config dir    : <config>
credentials   : <config>/credentials.yaml
policy        : <config>/policy.yaml
scopes        : project
key id        : key_v0uzv2hduoow6zclfi4kpg
secret        : RIL128RMMNsBGEEcnp3H1Qkl3ZRJb5xckqgUUw7uB-g
credential    : key_v0uzv2hduoow6zclfi4kpg.RIL128RMMNsBGEEcnp3H1Qkl3ZRJb5xckqgUUw7uB-g

To reach this node from a CLI, set:
  CONNECTOR_CLI_SERVER_URL=https://127.0.0.1:59999
  CONNECTOR_CLI_NODE_ID=node_4jlc54vvhsks2ymt2zw2sys724
  CONNECTOR_CLI_NODE_CREDENTIAL=key_v0uzv2hduoow6zclfi4kpg.RIL128RMMNsBGEEcnp3H1Qkl3ZRJb5xckqgUUw7uB-g
  CONNECTOR_CLI_CLIENT_CREDENTIAL=<the server's client credential>
```

Status: PASS. Both generation notices appeared, the secret was printed in full,
and the CLI block was present.

### Second start, same config directory, stdout is a terminal

Actual output: the same summary, the same node id, the same key id and the same
secret, and **neither** generation notice. The two lines
`a new node id was generated by this start` and
`a new credential was generated by this start` were absent.

Status: PASS. This is the half the earlier print-once rule failed: an operator who
restarted a Node had no way to recover the values except reading the file.

### Third start, stdout redirected to a file

Command:

```
... connector-node run > redirected.out 2> redirected.err
```

Actual stdout:

```
secret        : <secret:43 bytes>
credential    : key_v0uzv2hduoow6zclfi4kpg.<secret:43 bytes>
                (withheld because stdout is not a terminal; run the node in a
                 terminal to see it, or read the credentials file named above)
```

Measured with the real secret read from `credentials.yaml`:

| File | Occurrences of the plaintext secret |
|---|---|
| `redirected.out` | 0 |
| `redirected.err` | 0 |
| terminal capture from the first start | 3 (secret line, credential line, CLI block) |

Status: PASS. The protective branch works, and the count of 3 in the terminal
capture proves the same string is genuinely present when a human is watching, so
the zero in the redirected file is not a measurement of a string that never
appears.

### The printed values actually authenticate

A summary that prints a credential nobody can use would pass every check above.
The end-to-end run is what rules that out.

A Server was started on `127.0.0.1:18743` with `tunnel_token=e2e-tunnel-token` and
one client credential. A Node was started in a tmux session against it, and the
values were copied from the pane:

```
node id    : node_rxovl56takr3jzyiqajvctgmj4
credential : key_v1remtcwfv9nugd6-k-uya.Fyy3xWC-6Jp5clLuy3r2sC_wiCKkNnTqBXSQbb19ems
```

The Node logged `handshake accepted ... file_transport=binary-v1` and
`channel established`.

| Command | Expected | Actual | Status |
|---|---|---|---|
| `--scope project --path '' file.list` | one entry | `a.txt	file	15`, exit 0 | PASS |
| `--scope project --path a.txt file.read` | the file content | `hello from e2e`, exit 0 | PASS |
| `--scope project --path a.txt file.stat` | the metadata | name/type/size/mode/modified_at/is_symlink, exit 0 | PASS |

Status: PASS. The values printed at startup are the values a CLI needs.

### Two credentials

`credential add --key-id second-caller` was run, then the Node was restarted.

Actual output: both credentials printed in full, one `key id` / `secret` /
`credential` triple each, and the CLI block carried the first one plus
`(this node accepts 2 credentials; the first is shown)`.

Both credentials were then used against the running Node and both returned
`hello from e2e` with exit 0.

Status: PASS. The summary does not silently hide the second credential, and the
CLI block states which one it chose.

### No credentials

A `credentials.yaml` holding `version: 1` and `credentials: []` was used.

Actual output: `credential    : none; this node refuses every caller`, and the
`To reach this node from a CLI, set:` block was **omitted**.

Status: PASS. Printing a CLI block naming a credential that does not exist would
send the operator to an authentication error that reads like a Server problem.

### Embedded build

`bin/embedded-default run` with only `CONNECTOR_NODE_CONFIG_DIR` set, no policy
file and no Server URL.

Actual output: `policy        : embedded in this binary`, the compiled-in Server
URL, and the full summary including the secret.

Status: PASS. The `policy` line distinguishes a compiled-in policy from a file, so
an operator who cannot find `policy.yaml` is not left guessing.


## Claim: the summary prints on a real Windows console, on every start

Measured on the delivery path the operator actually uses, not on a hand-built
command line. Host: Windows Server 2022 at `192.168.2.6`, account
`Administrator`. Binary: the embedded drive-root build, 9607680 bytes, sha256
`a685425d5a674aeb2c69adfef66c25507f1f4632fab3728073510e2565983800`.

The console was a real pty, obtained by running the launcher inside tmux over
`ssh -tt`. A capture that redirects the ssh client's own stdout is not a
substitute: the pty screen buffer overwrites earlier lines, and the first two
attempts lost the whole summary block that way while the process itself was
healthy.

### Second start, existing credential

`run.cmd` with `CONNECTOR_NODE_CONFIG_DIR=C:\connector-drives\config`, where
`credentials.yaml` and `identity` already existed.

Actual output, verbatim:

```
=== connector-node ===
server        : ws://192.168.2.3:8743/channel
node id       : node_kt7pgg2v4yq47jtlosvio6jrb4
config dir    : C:\connector-drives\config
credentials   : C:\connector-drives\config\credentials.yaml
policy        : embedded in this binary
scopes        : c d e f g h i j k l m n o p q r s t u v w x y z
absent scopes : d e f g h i j k l m n o p q r s t u v w x y z
                (defined but the directory does not exist; every request
                 on these answers not_found until it exists and the node restarts)
key id        : drives-caller
secret        : rYINCtUIkXTYrE8Ju7mYeRrT9ccbEES4jsCmT__FB0E
credential    : drives-caller.rYINCtUIkXTYrE8Ju7mYeRrT9ccbEES4jsCmT__FB0E
To reach this node from a CLI, set:
  CONNECTOR_CLI_SERVER_URL=https://192.168.2.3:8743
  CONNECTOR_CLI_NODE_ID=node_kt7pgg2v4yq47jtlosvio6jrb4
  CONNECTOR_CLI_NODE_CREDENTIAL=drives-caller.rYINCtUIkXTYrE8Ju7mYeRrT9ccbEES4jsCmT__FB0E
  CONNECTOR_CLI_CLIENT_CREDENTIAL=<the server's client credential>
```

Neither generation notice appeared, which is the correct answer for a start that
found an existing identity and an existing credential. The secret is in full,
because stdout was a console.

Status: PASS.

### First start, empty config directory

`C:\connector-firstrun` did not exist before the run, confirmed with
`if exist`. The launcher set `CONNECTOR_NODE_CONFIG_DIR=C:\connector-firstrun\config`.

Actual output, verbatim, from the first two lines after `starting`:

```
a new node id was generated by this start
a new credential was generated by this start
=== connector-node ===
server        : ws://192.168.2.3:8743/channel
node id       : node_tcblvbjwrgc3mjc2tdg2zycdkm
config dir    : C:\connector-firstrun\config
credentials   : C:\connector-firstrun\config\credentials.yaml
policy        : embedded in this binary
scopes        : c d e f g h i j k l m n o p q r s t u v w x y z
absent scopes : d e f g h i j k l m n o p q r s t u v w x y z
key id        : key_s4wygkmfo2fugqzubr4u9w
secret        : yy4Y8H4tMzafF7sQzvCFqwMijSSPAE5nNEHQqVj7aYs
credential    : key_s4wygkmfo2fugqzubr4u9w.yy4Y8H4tMzafF7sQzvCFqwMijSSPAE5nNEHQqVj7aYs
To reach this node from a CLI, set:
  CONNECTOR_CLI_SERVER_URL=https://192.168.2.3:8743
  CONNECTOR_CLI_NODE_ID=node_tcblvbjwrgc3mjc2tdg2zycdkm
  CONNECTOR_CLI_NODE_CREDENTIAL=key_s4wygkmfo2fugqzubr4u9w.yy4Y8H4tMzafF7sQzvCFqwMijSSPAE5nNEHQqVj7aYs
  CONNECTOR_CLI_CLIENT_CREDENTIAL=<the server's client credential>
```

Status: PASS. "Start it and it works" holds on Windows: no `id` command, no
`credential add`, no configuration file. The values the operator needs appear on
the console the moment the process starts.

### The generated credential authenticates immediately

The values printed by that first start were used unchanged, with only the scheme
rewritten to `http://` because the Server is plaintext:

```
CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743
CONNECTOR_CLI_NODE_ID=node_tcblvbjwrgc3mjc2tdg2zycdkm
CONNECTOR_CLI_NODE_CREDENTIAL=key_s4wygkmfo2fugqzubr4u9w.yy4Y8H4tMzafF7sQzvCFqwMijSSPAE5nNEHQqVj7aYs
```

`connector-cli --scope c --path 'Windows/win.ini' file.stat` returned `rc=0`:

```
name	win.ini
type	file
size	92
mode	-rw-rw-rw-
modified_at	1620461911498
is_symlink	false
```

Status: PASS. A credential that appears on the console is a credential that
works, which is the property the requirement is actually about.

### Second start of the same config directory

The same launcher was run again against `C:\connector-firstrun\config`, which
now held the identity and the credential the first start created.

Actual output: the same `node id`, the same `key id`, the same `secret`, and
**neither** generation notice. The summary block was identical to the first
start apart from the two missing notice lines.

Status: PASS. A restart answers the same question as a first start, which is why
the summary is not gated on generation.

### The channel came up on every start

Each of the three starts reached the Server:

```
level=INFO msg="handshake accepted" node_id=... generation=12 file_transport=binary-v1
level=INFO msg="channel established" node_id=... server=ws://192.168.2.3:8743/channel
```

Status: PASS. The summary is printed before the dialer runs, so an operator sees
the values even when the Server is unreachable; here the Server was reachable and
the channel followed the summary.

### Cleanup

Both test processes were stopped by exact PID after the evidence was collected:
4832 (started 23:49:24, `C:\connector-drives\config`) and 5436 (started
23:52:06, `C:\connector-firstrun\config`). Verified `no connector-node processes
remain`. `C:\connector-firstrun` and the launcher `firstrun.cmd` were removed,
with the resolved path and every child printed before deletion, and the
surrounding directories asserted to still exist afterwards: `C:\connector-drives\config`,
the desktop binary, `C:\Users\Administrator\Desktop` and `C:\Windows` all
returned True.

## Limitations

- The terminal form was measured on Linux and on a real Windows console. The
  Windows measurement used the delivery launcher inside tmux over `ssh -tt`, so
  the console was a pty rather than a redirected stream. What remains unmeasured
  is a Windows console opened by a human double-clicking `run.cmd` in Explorer;
  the pty path exercises the same `isTerminal` branch, but the double-click path
  itself was not observed.
- The end-to-end run used a plaintext `http://` Server. At the time of that run the
  summary printed `CONNECTOR_CLI_SERVER_URL=https://...` regardless of the channel
  scheme, so the line was rewritten to `http://` by hand on Windows as well as on
  Linux. That defect is now fixed: the scheme is mapped, `ws://` prints `http://`
  and `wss://` prints `https://`. See
  `issues/issue-startup-summary-prints-https-for-a-plaintext-server.md`. The
  rewrite is no longer needed, and a later run must copy the printed line
  unchanged.
- The four `make check` e2e processes left behind by the suite were killed by
  exact PID after this evidence was collected; they were not part of the
  measurement.

## Evidence: the double-click output the user pasted, verified end to end

The user double-clicked `connector-node.exe` in Explorer and pasted the console
output. That closes the limitation recorded above: the double-click path was
observed, by the person who owns the machine, and the summary appeared in the
window with the secret in full.

The pasted identity was `node_rjkwb7zuy26vsajaj2pbnlssna`, key id
`key_ncofi1iiwzmd-vphaz4xuq`. The Server log confirms the channel really opened:
`channel established node_id=node_rjkwb7zuy26vsajaj2pbnlssna generation=17
file_transport=binary-v1`, and `channel closed` when the window was closed.

The pasted credential was then used from the build host. Every operation below
was run against the live Server with the Node started from the desktop binary.

| Operation | Result |
|---|---|
| `file.stat Windows/win.ini` | `rc=0`, `size 92`, `mode -rw-rw-rw-`, `is_symlink false` |
| `file.read Windows/win.ini` | `rc=0`, real content (`; for 16-bit app support`, `[fonts]`, …) |
| `file.list` on the scope root | `rc=0`, `$Recycle.Bin`, `Program Files`, `Users`, … |
| absent scope `d` | `rc=1`, `not_found` |
| undefined scope `nope` | `rc=1`, `denied` |
| traversal `../Windows/win.ini` | `rc=1`, `invalid_argument` |
| backslash `Windows\win.ini` | `rc=1`, `invalid_argument` |
| config dir `credentials.yaml` | `rc=1`, `denied` |
| missing file `nope.txt` | `rc=1`, `not_found` |

The credential the user pasted therefore authenticates, and the fence refuses the
cases it is supposed to refuse.

### The pasted summary contained the scheme defect

The pasted block printed `CONNECTOR_CLI_SERVER_URL=https://192.168.2.3:8743` while
the Server is plaintext HTTP. Measured with that exact line:

```
connector-cli: call server: Post "https://192.168.2.3:8743/v1/nodes/.../operations":
http: server gave HTTP response to HTTPS client
rc=1
```

With `http://` the same request returns `rc=0`. The user's paste is therefore the
first real-world sighting of the defect recorded in
`issues/issue-startup-summary-prints-https-for-a-plaintext-server.md`, and it is
the reason that issue exists rather than a hypothetical.

### The rebuilt binary prints the right scheme

The desktop binary was replaced with the fixed build, 9608192 bytes, sha256
`538135857bf006ebd37ca029cf7e40d1f9c2d0ae64d01c78e0d19c8141918fbb`, matching the
build host. Started from that binary with `ws://192.168.2.3:8743/channel`, the
summary printed:

```
CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743
```

That printed line was used unchanged and returned `rc=0` for `file.stat` and
`file.read`. The fix is verified on the platform it was reported on, not only in a
unit test.

### The README contradicted the binary

`README.txt` on the desktop still said `https://` on the line it told the reader to
copy, so a reader following the README would have hit the TLS error the binary no
longer produces. Corrected to `http://` and extended with the scheme rule: the
scheme follows the channel address, `ws://` prints `http://`, `wss://` prints
`https://`, and changing it by hand fails with `server gave HTTP response to HTTPS
client`. Transferred and verified by md5 `a2265313d8705372c82723d961cbdc87` on both
sides.

A document that tells the reader to copy a line the product no longer prints is the
same class of defect as the original: the reader follows the document, not the
binary.

## Finding: a copy of the config directory is served in full

The deny list refuses the Node's own config directory by identity, so the real
directory and everything inside it are refused. A **copy** of that directory is a
different inode, so it is not refused, and a caller with a valid node credential
reads the copy in full.

Measured on the Windows host with the drive-root Node, scope `c` covering `C:\`:

```
file.list  Users/Administrator/AppData/Roaming
  -> topsailai-connector.bak-bearer-20261111   dir   0
     (the real topsailai-connector is correctly omitted)

file.read  .../topsailai-connector.bak-bearer-20261111/identity
  -> node_3var5wpfhv5w7h7xsw7hdnhffi.wo42vslxitw3472xjvo5vegyvk4mwp3elddiqcit3m3jbhxvo5ca
  rc=0
```

That copy held a pre-HMAC bearer credential, which is dead: using it returns
`unauthenticated`. The mechanism is not limited to that copy, so the live
`credentials.yaml` was copied into the backup directory and read back through the
fence:

```
file.read  .../topsailai-connector.bak-bearer-20261111/credentials.yaml
  -> version: 1
     credentials:
         - key_id: key_ncofi1iiwzmd-vphaz4xuq
           secret: 9FakrYd6-B1UFcAGNDvs6N-nYUyTuUUNuVtPMPNWcik
  rc=0
```

That is the operator's live secret, and it never expires. The copy was removed after
the measurement; the backup directory now holds only `identity`.

The behaviour is a deliberate consequence of answering by identity rather than by
name, and `docs/permission-design.md` states it for a look-alike that holds nothing.
It does not cover the case that occurs in operation: an operator copies the config
directory before an upgrade, or a packaging script leaves a `.bak-<date>` sibling,
and the copy holds a real credential. The rule then protects the original and serves
the copy.

Recorded as `issues/issue-a-copy-of-the-config-directory-is-served.md` with four
options and no decision, because every option trades a false refusal against a real
leak. The skill now warns the operator, which is the only option with no false
refusal.

The detection gap is worth stating: no test creates a copy of the config directory,
the design document presents the look-alike behaviour as settled, and the skill did
not mention backups at all before this change. A hazard that is documented as a
consequence reads as reviewed, and a reviewer who reads it as reviewed does not ask
what happens when the look-alike holds a credential.
