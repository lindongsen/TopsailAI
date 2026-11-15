# Author: DawsonLin
# Purpose: Container image for the Connector Server.
#
# The Server binary is built outside the image and copied in. A `golang:` builder
# stage is the usual shape, but the deployment host cannot reach Docker Hub, so a
# builder stage would fail at the pull rather than at the build. Building with
# `make build-server` and copying the result keeps the image reproducible from a
# source tree that `make check` has already verified, and it keeps the image free
# of a toolchain that would never run in it.
#
# The base image is a build argument because the only reachable registry on this
# deployment host is a local one. A deployment with Docker Hub access passes
# BASE_IMAGE=alpine:3.20 and gets the same image from the same Dockerfile.

ARG BASE_IMAGE=alpine:latest
FROM ${BASE_IMAGE}

# The Server holds no state. It forwards a request and relays the answer, and it
# keeps no copy of a Node token, so there is nothing to persist and the container
# can run with a read-only root filesystem.
COPY connector-server /usr/local/bin/connector-server

# A non-root user, because the Server needs no privilege: it binds one port above
# 1024 and reads nothing from the host. The numeric form is used because the
# image has no passwd entry for it and a name would have to be resolved.
USER 65534:65534

# One listener serves both surfaces: the channel at /channel and the CLI API at
# /v1/. There is no second port to expose, because the two surfaces share the
# routing registry and a second port would not isolate state.
EXPOSE 8443

ENTRYPOINT ["/usr/local/bin/connector-server"]
CMD ["run"]
