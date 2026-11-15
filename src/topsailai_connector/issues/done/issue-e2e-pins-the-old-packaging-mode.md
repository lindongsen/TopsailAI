---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-14
resolved: 2026-11-14
---

# The packaging step is untested, and the only packaging test pins the old mode

## Symptom

`make check` passes, but nothing in it builds the packaging mode a user now gets
by default, and nothing verifies that the linker flags which carry the embedded
configuration actually reach the binary.

`Makefile:115` sets `PACKAGE_EMBED_CONFIG ?= 1`, so `make package` produces one
executable. The only automated test that exercises the delivery path,
`tests/e2e/verify_package.sh`, overrides that default in both of its packaging
calls:

```
tests/e2e/verify_package.sh:126:		PACKAGE_EMBED_CONFIG=0
tests/e2e/verify_package.sh:268:			PACKAGE_EMBED_CONFIG=0
```

So the suite proves the zip path works and proves nothing about the embedded
path, which is the path a user reaches without passing any flag.

## What is already covered, and what is not

This distinction matters, because the embedded *behaviour* is well tested and the
embedded *packaging* is not tested at all. An earlier draft of this issue claimed
the behaviour was untested; that was wrong, and the correction is recorded here so
the same mistake is not repeated.

Covered by unit tests, 15 in total:

| Test file | Tests | What it proves |
|---|---|---|
| `internal/node/embedded/embedded_test.go` | 6 | `Enabled` is false in a normal build and true for any embedded value; `CarriesSecret` tracks only the token; `Policy` returns nil when nothing was embedded, decodes a document, refuses malformed base64 |
| `internal/node/embedded_config_test.go` | 9 | Embedded values are used when the environment is empty; the environment wins over them; a policy file is refused when the policy is embedded; a malformed embedded policy is refused; a secret is still required without an embedded one; embedded authority bytes get the same validation as a file; the scopes it defines are opened; the running executable is refused when the binary carries a secret and served when it does not |

Also covered: the config-directory fallback to the platform directory, at
`internal/node/store_extra_test.go:115`, which asserts the resolved path ends in
`DefaultConfigDirectoryName`.

Not covered, and this is the actual gap:

1. **That `make package` with no flag produces a single executable rather than a
   zip.** The assertion must be on the artifact shape, because a test that sets
   `PACKAGE_EMBED_CONFIG` to today's default would pass again after the default
   changed.
2. **That the `-X` linker flags land in the binary.** `packaging/build-package.sh:321-324`
   passes three values by package path:

   ```
   LDFLAGS="-X topsailai_connector/internal/node/embedded.ServerURL=$CHANNEL_URL"
   LDFLAGS="$LDFLAGS -X topsailai_connector/internal/node/embedded.PolicyBase64=$POLICY_B64"
   LDFLAGS="$LDFLAGS -X topsailai_connector/internal/node/embedded.TunnelToken=$PACKAGE_TUNNEL_TOKEN"
   ```

   A `-X` whose package path does not match the module path is silently ignored by
   the linker. The build succeeds, the binary starts, and the configuration is
   simply absent. No unit test can see this, because the unit tests set the
   variables directly rather than through the linker. `grep -rn 'LDFLAGS'` over
   `tests/` and `internal/` returns only a comment in `embedded.go`, so nothing
   checks the wiring.
3. **That the packaged binary starts with no configuration file and no
   environment variable.** This is the promise the embedded mode makes, and it is
   the one a recipient depends on.

## Evidence gathered by hand

The default was flipped in `f0dae93a`. The three packaging modes were verified by
hand at that time, and re-verified while writing this issue:

| Command | Result |
|---|---|
| `make package` | one executable, no zip written |
| `make package-zip` | zip, 5127174 bytes |
| `make package PACKAGE_EMBED_CONFIG=true` | refused, lists the two accepted spellings |
| `make package` without `PACKAGE_SERVER_URL` | refused, `PACKAGE_SERVER_URL is required` |

The embedded binary was then run with a minimal environment:

```
env -i HOME=/tmp/pkgprobe-home CONNECTOR_NODE_TUNNEL_TOKEN=dummy-token-value \
  ./bin/connector-node-linux-amd64 run
```

```
msg="connector-node ready" node_id=node_j6ofkoes5rpjjrbohlizgta7ri scopes=[project]
config="server=ws://127.0.0.1:18444/channel tunnel_token=<secret:17 bytes>
config_dir=/tmp/pkgprobe-home/.config/topsailai-connector policy=embedded"
msg="channel ended" error="dial ws://127.0.0.1:18444/channel: connect: connection refused"
```

That output proves all three `-X` values arrived: the server URL, the policy (it
resolved scope `project` to `/tmp/pkgprobe`), and the token (reported as 17 bytes,
the length of the dummy). It also proves `policy=embedded` and that the config
directory fell back to the platform location.

## Two hazards a naive test would hit

These were found by running the packaging step, not by reading it.

**A stale zip survives an embedded build.** The `rm -f "$ZIP_PATH"` that clears a
previous artifact sits inside the zip branch of `build-package.sh`, so an embedded
build never touches it. Measured:

```
before: bin/connector-node-linux-amd64.zip  19:11:24  md5 de81b266...
after:  bin/connector-node-linux-amd64.zip  19:11:24  md5 de81b266...
        bin/connector-node-linux-amd64      20:28     (new executable)
```

Same mtime, same checksum. A test that asserts "no zip exists after `make
package`" would therefore fail on any machine that had previously built a zip, and
would pass on a clean checkout. The assertion has to be on the artifact the run
produced, not on the absence of a file another run may have left.

This is also a user-facing hazard: an operator who runs `make package-zip` and
then `make package` ends up with both artifacts in `bin/`, and the zip is the
older one. Handing over the zip while believing it is the fresh build is a
mistake the build does not prevent.

**`env -i` alone is not enough.** The binary refuses to start with no environment
at all:

```
connector-node: resolve the platform config directory: neither $XDG_CONFIG_HOME
nor $HOME are defined
```

So "starts with no environment variable" is true of the *configuration* variables
and false of the environment as a whole. A test must supply `HOME` or
`XDG_CONFIG_HOME`, otherwise it tests the platform directory resolution rather
than the embedded configuration.

## Proposed fix

Add a packaging check that:

1. Builds with no `PACKAGE_EMBED_CONFIG` set, so the default is what is tested.
2. Records the artifact path the run reports, and asserts it is a single
   executable rather than a zip. Do not assert the absence of a zip.
3. Starts that artifact with `HOME` set and no `CONNECTOR_NODE_*` variable, and
   asserts the startup log reports `policy=embedded` and the configured server
   URL. That is the only check that can catch a `-X` whose package path drifted.
4. Reads one file through the CLI, so the artifact is proven usable rather than
   merely startable.

Keep the existing zip check as the explicit `PACKAGE_EMBED_CONFIG=0` case, so both
modes are covered and the default is covered by the absence of a flag rather than
by a value that happens to match today's default.

## Prevention

- A test that pins a mode must be paired with a test that exercises the default,
  otherwise flipping the default silently moves the test off the path users take.
- A linker flag is configuration that no unit test can see. Anything passed by
  `-X` needs one check that runs the built artifact and reads the value back.
- Assert on the artifact a run produced, not on the absence of a file another run
  may have left behind.

## Related defect: two comments still describe the old default

The same commit that flipped the default, `f0dae93a`, left two comments in the
Makefile describing the previous behaviour:

```
Makefile:54:  # Packaging inputs. `make package` builds one zip that a user unzips and starts,
Makefile:289: # package builds one zip that a user unzips and starts, and that the operator can
```

Both are wrong: `make package` now produces one executable. The help text at
`Makefile:163` and the README at `README.md:166` were updated correctly, so the
Makefile is the only place that still says zip.

This is the same root cause as the missing test: the default changed and the
things that describe the default did not all follow. A reader who trusts the
comment above the target will build the wrong mental model of what the command
produces, and the comment sits directly above the target they are about to run.

The fix is to correct both comments to describe one executable, and to name
`make package-zip` as the way to get the zip.

## Resolution

Both parts are fixed in one commit.

`tests/e2e/verify_package.sh` now has a section that builds with **no**
`PACKAGE_EMBED_CONFIG` at all, so it follows the default rather than a value that
happens to equal it. It reads the artifact path from the `package: wrote` line,
asserts that path is executable and is not a zip, starts it with `env -i` and a
`HOME` but no `CONNECTOR_NODE_*` variable, and asserts four things from the
startup log and one CLI read:

| Assertion | What it catches |
|---|---|
| The reported artifact is executable and not `.zip` | The default silently reverting to a zip |
| `policy=embedded` | A `PolicyBase64` `-X` drift |
| `server=ws://127.0.0.1:<port>/channel` | A `ServerURL` `-X` drift |
| `scopes=[project]` | An embedded policy that defines a different scope |
| `file.read` returns the fixture content | An artifact that starts but cannot serve |

The existing zip checks are unchanged, so both modes are covered: the zip by an
explicit `PACKAGE_EMBED_CONFIG=0`, the default by passing nothing.

`Makefile:54` and `Makefile:289` now describe one executable and name
`make package-zip`. The `build-node` dependency comment was corrected too: it is
load-bearing only for the zip, because the default mode creates the identity on
the target machine.

### Verification

`make check` returned 0 with zero `FAIL`, and the new section ran inside it:

```
--- the default packaging mode is one executable, not a zip ---
verify: the default packaging mode produced one executable, .../bin/embedded-default
verify: the embedded policy, Server URL and scopes all reached the binary
verify: the default artifact served a file
verify: the default artifact refused a traversal path, as expected
verify: all bundle checks passed
```

Four mutations were applied to `packaging/build-package.sh` and each was caught.
The file was restored from a backup after each one, and `git status` on it was
clean before the next.

| Mutation | Result | Caught by |
|---|---|---|
| `embedded.ServerURL` → `embedded.ServerURLX` | RC=1 | `did not connect` |
| `embedded.PolicyBase64` → `embedded.PolicyBase64X` | RC=1 | `did not connect`; the log said `policy file is missing` |
| Scope name renamed in the policy only | RC=1 | `did not connect`; the log said the grant names an undefined scope |
| Scope name renamed in both the policy and the grant | RC=1 | **`the embedded policy did not define the project scope`** |

The fourth mutation is the one that proves the `scopes=[project]` assertion is
load-bearing rather than decoration: the binary started, connected and reported
`scopes=[projectX]`, so only that assertion could catch it.

The first three were caught at startup rather than by the assertion named for
them. That is honest and expected: a missing Server URL or a missing policy stops
the Node before it connects, so the connection assertion fires first. The
assertions are still worth keeping, because they name the specific value that
went missing instead of leaving a generic "did not connect".

### A defect found while verifying

The live runs exposed an unrelated defect: a Node stopped normally logs
`identity changed; closing the channel authenticated with the retired pair`, even
though the identity file's checksum never changed. It is recorded separately in
`issue-shutdown-logs-a-false-identity-change.md` and is not fixed here.
