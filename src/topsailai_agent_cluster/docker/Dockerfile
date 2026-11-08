# Author: DawsonLin
# Purpose: Build the Agent Cluster server as a self-contained container image.
#
# The server is a static Go binary: SQLite comes from the pure-Go
# modernc.org/sqlite driver, so CGO is disabled and the runtime image needs no
# libc toolchain. TLS material and the SQLite database are mounted at run time
# instead of being baked in, so one image serves every deployment and rotating a
# certificate never requires a rebuild.
#
# The container listens on every interface. A loopback-only bind would make the
# published port unreachable from other containers, which is the whole point of
# publishing it: endpoints reach the server through a bridge gateway address and
# never depend on the container's own IP, which changes on every recreate.
#
# The runtime stage installs no packages. This host's resolver forwards
# dl-cdn.alpinelinux.org to unreachable public resolvers, so `apk add` fails with
# a DNS lookup error; busybox already provides addgroup, adduser and wget, and the
# CA bundle is copied from the build stage. A runtime stage that needs no network
# also builds reproducibly on an air-gapped host.

# syntax=docker/dockerfile:1

FROM golang:1.25-alpine AS build

WORKDIR /src

# Dependencies are copied first so a source-only change reuses the module layer.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# -trimpath keeps host paths out of the binary and -s -w drops the symbol table,
# which is safe because the image ships no debugger.
RUN CGO_ENABLED=0 GOOS=linux go build \
        -trimpath -ldflags='-s -w' \
        -o /out/agent-cluster-server ./src/main/agent-cluster-server

FROM alpine:3.20.2

# The CA bundle is copied rather than installed so the runtime stage performs no
# network access. It is only needed if the server ever dials an external TLS
# peer; the endpoint certificates it verifies come from the mounted ca.pem.
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

COPY --from=build /out/agent-cluster-server /opt/agent-cluster/bin/agent-cluster-server

# A fixed unprivileged identity keeps the container from running as root. The
# state and log directories are owned by it so a mounted volume is writable
# without a chown on the host.
RUN addgroup -S -g 10001 agent-cluster \
    && adduser -S -u 10001 -G agent-cluster -h /var/lib/agent-cluster agent-cluster \
    && mkdir -p /etc/agent-cluster/certs /var/lib/agent-cluster /var/log/agent-cluster \
    && chown -R agent-cluster:agent-cluster /var/lib/agent-cluster /var/log/agent-cluster

# The database path and the TLS paths are fixed here so the run command only has
# to supply the token and the mounts. Logs go to stderr because a container
# should not own a log file: the Docker log driver rotates it.
ENV AGENT_CLUSTER_API_LISTEN_ADDR=:53680 \
    AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=:53943 \
    AGENT_CLUSTER_DATABASE_PATH=/var/lib/agent-cluster/server.sqlite \
    AGENT_CLUSTER_TLS_CA_FILE=/etc/agent-cluster/certs/ca.pem \
    AGENT_CLUSTER_TLS_CERTIFICATE_FILE=/etc/agent-cluster/certs/server.pem \
    AGENT_CLUSTER_TLS_KEY_FILE=/etc/agent-cluster/certs/server-key.pem \
    AGENT_CLUSTER_LOG_OUTPUT=stderr

USER agent-cluster

EXPOSE 53680 53943

# /healthz is served without authentication, so the probe needs no token.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:53680/healthz || exit 1

ENTRYPOINT ["/opt/agent-cluster/bin/agent-cluster-server"]
