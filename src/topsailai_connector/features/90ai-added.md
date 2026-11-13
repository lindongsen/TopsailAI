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
