# Author: DawsonLin
# Purpose: Build the Agent Cluster server as a self-contained container image.
#
# The server is a static Go binary: SQLite comes from the pure-Go
# modernc.org/sqlite driver, so CGO is disabled and the runtime image needs no
# libc toolchain. TLS material and the SQLite database are mounted at run time
# instead of being baked in, so one image serves every deployment and rotating a
# certificate never requires a rebuild.
#
# The image uses the same /opt/agent-cluster tree as the Debian package, and every
# mount point is the same path on both sides. A container that kept state in
# /var/lib while the package kept it in /opt/agent-cluster forced an operator to
# translate between two names for one file, and made a container and a package
# look like different products. The image still differs from a package where the
# difference is real: it carries no conffile because it is configured by
# environment variables, and it writes no pid file because the container runtime
# supervises the process.
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
# state and log directories are owned by it here so the image is usable on its
# own; a bind mount replaces that ownership with the host directory's, which is
# why the run command grants it again per entry instead of recursively.
#
# The directory tree mirrors the package layout under /opt/agent-cluster, so the
# container path and the host path are the same string and an operator inspecting
# either side sees one shape. conf/ and run/ are deliberately absent: the image
# takes its configuration from environment variables rather than a conffile, and
# the container runtime supervises the process so no pid file is written. Creating
# them empty would suggest a node.conf or a pid file is honoured here, which it is
# not.
RUN addgroup -S -g 10001 agent-cluster \
    && adduser -S -u 10001 -G agent-cluster -h /opt/agent-cluster/data agent-cluster \
    && mkdir -p /opt/agent-cluster/bin /opt/agent-cluster/certs \
        /opt/agent-cluster/data /opt/agent-cluster/logs \
    && chown -R agent-cluster:agent-cluster /opt/agent-cluster/data /opt/agent-cluster/logs

# The database path and the TLS paths are fixed here so the run command only has
# to supply the token and the mounts. Every path is under /opt/agent-cluster,
# which is the same directory the package uses, so the container path and the
# host path are identical. Logs go to stderr because a container should not own a
# log file: the Docker log driver rotates it.
ENV AGENT_CLUSTER_API_LISTEN_ADDR=:53680 \
    AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=:53943 \
    AGENT_CLUSTER_DATABASE_PATH=/opt/agent-cluster/data/server.sqlite \
    AGENT_CLUSTER_TLS_CA_FILE=/opt/agent-cluster/certs/ca.pem \
    AGENT_CLUSTER_TLS_CERTIFICATE_FILE=/opt/agent-cluster/certs/server.pem \
    AGENT_CLUSTER_TLS_KEY_FILE=/opt/agent-cluster/certs/server-key.pem \
    AGENT_CLUSTER_LOG_OUTPUT=stderr

USER agent-cluster

EXPOSE 53680 53943

# /healthz is served without authentication, so the probe needs no token.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:53680/healthz || exit 1

ENTRYPOINT ["/opt/agent-cluster/bin/agent-cluster-server"]
