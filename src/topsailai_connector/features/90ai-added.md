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
