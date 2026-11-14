---
maintainer: AI
author: DawsonLin
---

# AI-added features

## Container deployment for the Server

`docker/Dockerfile` and `docker/docker-compose.yaml` deploy the Server as a
container. The binary is built outside the image and copied in, because the
deployment host cannot reach Docker Hub and a `golang:` builder stage would fail
at the pull rather than at the build. The base image is a build argument so a
host with registry access can pass `BASE_IMAGE=alpine:3.20` and get the same
image from the same file.

The container runs as a non-root user with a read-only root filesystem, a tmpfs
at `/tmp`, and `no-new-privileges`. The Server holds no state, so a writable
root would only be a place for a future change to start persisting something the
design forbids. Both secrets arrive through `env_file`, never through the compose
file, so a committed compose file cannot leak one.

One port is published, because one listener serves both the channel at `/channel`
and the CLI API at `/v1/`.

## An explicit opt-in for a whole-volume scope

A policy may carry `allow_filesystem_root: true`, which lets one scope map to a
filesystem root such as `C:\` or `/`. Without the key the Node refuses such a
scope at startup, so a policy written before the key existed behaves exactly as
it did before.

The key relaxes exactly two startup refusals: the volume-root refusal and the
refusal of a scope that overlaps the Node's own config directory. The second
follows from the first rather than being a separate permission, because a scope
rooted at `C:\` necessarily contains the config directory, so keeping the overlap
refusal would make the opt-in unusable. The home-directory refusal is never
relaxed, because the Node refuses it unconditionally and a bundle that allowed it
would fail on the recipient's machine instead of at packaging time.

The decision belongs to whoever packages the bundle, not to whoever receives it.
The bundle's start script writes the key only when the bundle was built with
`PACKAGE_ALLOW_FILESYSTEM_ROOT=1`, and the value is recorded in an
`allow_filesystem_root` file beside the bundle so the decision is visible rather
than implied. The variable accepts only `1`, `0` or an empty value; `true` and
`yes` are refused, because a typo silently treated as "off" would produce a
bundle that rejects the volume root the operator asked for.

The protection does not disappear when the key is set. A whole-volume scope
necessarily contains the config directory, so the Node denies that directory by
resolved path, omits it from a listing, and refuses a junction or symlink that
resolves to it. Measured on the live Windows deployment: reading
`config\identity`, `config\tunnel_token` and `config\policy.yaml` through the
volume scope all return `denied`, listing the config directory returns `denied`,
and the directory does not appear in its parent's listing.

## A packaging mode that embeds the configuration in the binary

`make package-embedded` builds one executable that starts and connects with no
configuration file and no environment variable. The Server URL, the policy
document and the `tunnel_token` are compiled in with `-ldflags -X`, so the
recipient runs the binary and the Node is reachable.

The identity pair is deliberately not embedded. It is generated on first start,
polled every second and rewritten by `regenerate`, so an embedded pair would have
no file to watch or rewrite; and two machines running the same binary would share
one `node-id`, which the Server's `node_id -> connection` registry would resolve by
evicting the first. The binary therefore still creates its own pair on first start
and prints it once.

Environment variables win over embedded values field by field, so an operator can
repoint the same binary without a rebuild. The policy is the exception: a build
that embedded a policy refuses `CONNECTOR_NODE_POLICY_FILE`, because an embedded
policy is a whole document and a file path would silently replace every scope and
grant.

Embedding the `tunnel_token` makes the binary a Server-wide credential, so a build
that carries it adds its own executable to the deny list. Without that entry a
scope containing the binary would serve it: the live Windows deployment maps one
scope to `C:\`, which contains the install directory, so a remote caller could read
the token out of the file. The entry uses `os.Executable()` rather than
`os.Args[0]`, because the deny list compares by file identity and the latter is
whatever the launcher typed. It is conditional on the token being present, so a
normal build still serves its own install directory.

The embedded policy is decoded by `policy.ParseBytes`, the same strict decoder the
file path uses, and the scope-opening rules live in one function shared by both
paths, so the fence cannot be configured differently depending on how the policy
arrived. Scope paths are written exactly as the packaging step received them and
are never resolved on the build host, because the binary runs on another machine.

`-X` stores the value as plain text, so `strings` recovers the token. That is
documented rather than encoded away: base64, compression and obfuscation all decode
with the same command, and encryption would need a key the binary must also carry.
The protection that matters is the deny list, which stops a remote caller; a local
user holding the file already has the secret.
