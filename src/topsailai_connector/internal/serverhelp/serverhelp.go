// Package serverhelp holds the help text for the connector-server binary.
//
// The text lives in its own package rather than in main for the same reasons as
// nodehelp: the entry point stays readable, and the text can be tested without
// starting a process, which is what lets a guard test compare it against the source
// for every environment variable and every subcommand.
package serverhelp

import "strings"

// programPlaceholder is replaced with the program name in every text.
//
// The texts are plain strings with a placeholder rather than `fmt` templates, because
// a help text is full of `%` characters in its examples and every one of them would
// have to be escaped. A missed escape prints `%!s(MISSING)` to the person asking for
// help, which is the worst possible place for that defect.
const programPlaceholder = "{{program}}"

// Main returns the complete help for the binary.
//
// The text is complete on purpose: every subcommand, every environment variable, the
// two surfaces the one listener serves, and every exit status. A help text that lists
// the variables but not which of them are required leaves an operator discovering the
// requirement from a startup failure, and one that does not say the CLI API shares the
// channel's port leaves them opening a second port that buys nothing.
func Main(program string) string {
	return replaceProgram(program, `NAME
  {{program}} - accept Node connections and forward the operations they advertise

SYNOPSIS
  {{program}} [run]
  {{program}} cli [FLAGS] OPERATION
  {{program}} help [SUBCOMMAND]
  {{program}} --help
  {{program}} --version

DESCRIPTION
  The Server runs in the cloud. A Node on a personal computer dials out to it, keeps
  the link open and serves only the operations its local policy allows. The Server
  never dials a Node, so a personal computer needs no inbound port, no public address
  and no firewall change.

  The Server is a pipe for the node proof, not a holder of the node secret. It
  verifies the client credential, forwards the node proof byte for byte and keeps no
  copy. That is the single rule the whole design rests on: a Server that received a
  Node's secret would yield every Node credential at once if it were compromised.

  The Server holds no scope list and no permission list. It cannot add a scope, widen
  a grant or mark a request as pre-approved. The Node decides both which area may be
  touched and which action may be taken there, so a request the Server has already
  authenticated is still unauthenticated as far as the Node is concerned.

  One listener serves two surfaces, because they share the routing registry and a
  second port would not isolate state:

    /channel    where a Node dials in
    /v1/        the CLI API, where an operator calls an operation

  One listener means one TLS certificate, one firewall rule and one proxy entry. A
  deployment that must keep the CLI API unreachable from the internet blocks /v1/ at
  the reverse proxy rather than opening a second port.

SUBCOMMANDS
  run
        Load the configuration, validate both secrets and serve the two surfaces until
        the process is asked to stop. This is the default, so a bare {{program}} with
        no subcommand runs it.

        Every configuration failure here is a startup failure. A Server that started
        with a missing or short secret would authenticate callers it should refuse, and
        the mistake would surface as a successful request rather than as a refusal.

  cli [FLAGS] OPERATION
        Call one operation on a Node through this Server. This is the caller's side of
        the arrangement: it signs one request with a client credential and a node
        credential, names the Node it wants, and prints the result.

        The operations are file.list, file.stat and file.read. file.write and
        command.exec are refused in this version.

        Run {{program}} help cli for the flags, the environment variables and the
        exit statuses. That page is complete for running a request, and it is not
        repeated here, because two copies of one interface drift apart.

  help [SUBCOMMAND]
        Print this help, or the help for one subcommand.

ENVIRONMENT
  Every variable carries the CONNECTOR_SERVER_ prefix.

  Required:

    CONNECTOR_SERVER_TUNNEL_TOKEN
        The secret a Node must present in hello to open a channel. An absent or empty
        value fails startup rather than disabling the check. At least 16 bytes, and a
        shorter value is refused at startup with the length it received, so a
        placeholder such as "test" fails before the listener opens.

    CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE
        Path to the YAML file holding the client credentials this Server accepts. A
        missing, empty or unreadable file fails startup. Must be an absolute path; a
        relative one is refused, because it would resolve differently depending on the
        directory the Server was started from.

  Optional:

    CONNECTOR_SERVER_LISTEN
        Address to listen on. Default :8443. One listener serves both /channel and
        /v1/, so there is no second port to configure.

    CONNECTOR_SERVER_TLS_CERT
        Path to the TLS certificate. Required unless TLS is terminated in front of the
        Server. Must be an absolute path.

    CONNECTOR_SERVER_TLS_KEY
        Path to the TLS private key. A path, not the key itself. Must be an absolute
        path. Setting one of the certificate variables without the other is a startup
        failure, because a key without a certificate cannot serve and a certificate
        without a key cannot either.

    CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS
        How far a client proof timestamp may differ from this machine's clock. Default
        60. At least 1, at most 600.

    CONNECTOR_SERVER_REPLAY_CAPACITY
        How many unexpired client nonces are recorded. Default 65536. A full cache
        refuses new proofs rather than evicting a live nonce, because evicting one
        would re-open the replay window it exists to close.

    CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS
        How long to wait for a Node before answering node_timeout. Default 30. At
        least 1, at most 3600.

    CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER
        How many requests one caller may have in flight at once. Default 2. At least 1.

    CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE
        How many requests one Node may have in flight at once. Default 4. At least 1.

    CONNECTOR_SERVER_MAX_IN_FLIGHT
        How many requests the whole Server may have in flight at once. Default 64. At
        least 1.

    CONNECTOR_SERVER_ADMISSION_WAIT_MS
        How long a request may wait for a slot before it is refused with overloaded.
        Default 200. Zero or more, at most 5000. Zero is a meaningful setting, not
        "unset": it refuses immediately rather than waiting.

  The three in-flight limits answer three different questions. A Server-wide bound
  alone stops unbounded growth but lets one caller occupy every slot. A per-caller
  bound alone lets many callers aimed at one Node saturate that Node. The per-Node
  bound is the one that protects the personal computer the Node runs on, which is the
  machine this system exists to keep usable.

  A value below one is refused at startup rather than clamped. A zero limit would
  refuse every request, and a Server that refuses everything looks like a Server that
  is working and denying, which is the most expensive kind of misconfiguration to
  diagnose.

  The Server has no variable for a Node credential secret, because it never receives
  one. There is no CONNECTOR_SERVER_NODE_SECRET and no equivalent. A deployment that
  tries to configure one has misunderstood the model.

  The client credentials are a file rather than a variable because there can be
  several of them and each is rotated on its own schedule. The file holds key_id and
  secret pairs, is parsed strictly so an unknown key is a startup failure, and is
  capped at 1 MiB.

FIRST RUN
  The Server cannot create its own client credential file: this binary has no
  credential subcommand, because the file format has one implementation and it lives
  in the Node binary. Create the file with connector-node, then point the Server at
  it:

    CONNECTOR_NODE_CONFIG_DIR=/etc/connector/server-client \
      connector-node credential add --key-id operator-dawson
    -> operator-dawson.<secret>        copy this; it is printed once

    CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> \
    CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE=/etc/connector/server-client/credentials.yaml \
      {{program}} run

  CONNECTOR_NODE_CONFIG_DIR is a Node variable, used here only because the Node
  binary is what writes the file. The Server never reads it.

  The file is written with mode 0600 and is owned by whoever ran that command. A
  Server that runs as a different user, such as a container running as nobody, must
  have the file's owner changed to that user, or it cannot read the file it requires
  and refuses to start.

  A Node's own credential is created on the Node, with the same command and a
  different config directory. The Server never receives it and has no variable for
  it.

EXIT STATUS
  0   The Server stopped after a signal. A help request also exits 0.
  1   Startup failed, or the listener ended with an error.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed startup without parsing the text.

EXAMPLES
  Start the Server with TLS terminated in front of it:

    CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> \
    CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE=/etc/connector/client-credentials.yaml \
    CONNECTOR_SERVER_LISTEN=:8443 \
      {{program}} run

  Start it with its own certificate:

    CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> \
    CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE=/etc/connector/client-credentials.yaml \
    CONNECTOR_SERVER_TLS_CERT=/etc/connector/tls.crt \
    CONNECTOR_SERVER_TLS_KEY=/etc/connector/tls.key \
      {{program}} run

  Call a Node. Every value below is required, and the flags come before the
  operation name:

    CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743 \
    CONNECTOR_CLI_CLIENT_CREDENTIAL=operator-dawson.<secret> \
    CONNECTOR_CLI_NODE_ID=node_7f3a...9c1e \
    CONNECTOR_CLI_NODE_CREDENTIAL=bundle-caller.<secret> \
      {{program}} cli --scope project --path notes.md file.read

  Read the flags the cli subcommand accepts:

    {{program}} help cli

SEE ALSO
  {{program}} help run, help cli
        The page for one subcommand.

  {{program}} --version
        The build this binary came from, which is what to quote in a bug report.

  The Node side of the same system is connector-node, which is also the binary that
  writes the client credential file this Server requires. The caller side is
  connector-cli, or the cli subcommand of this binary.
`)
}

// Run returns the help for the run subcommand.
func Run(program string) string {
	return replaceProgram(program, `NAME
  {{program}} run - serve the channel and the CLI API from one listener

SYNOPSIS
  {{program}} run
  {{program}}

DESCRIPTION
  Loads the configuration, validates both secrets and serves until the process is
  asked to stop.

  Every failure here is a startup failure. A Server that started with a missing or
  short secret would authenticate callers it should refuse, and the mistake would
  surface as a successful request rather than as a refusal. That is why an empty
  secret is refused instead of being read as "authentication disabled".

  The routing registry is created once and handed to the listener, so the channel
  surface and the CLI surface share one table. Two registries would let a Node
  register into one while the CLI looked in the other, and the symptom would be a
  Node that looks connected and answers node_offline.

  The process stops on SIGINT or SIGTERM. The shutdown closes the HTTP server and
  every live channel, so a Node that is mid-request is answered instead of being cut
  off. A Server that exited without closing its listener would leave the port bound
  until the operating system reclaimed it, which on Windows is long enough to make an
  immediate restart fail.

  The startup log line names the protocol version, the listen address and the
  configuration with every secret redacted. A configuration dump that echoed a secret
  would be a credential leak with a helpful name.

ENVIRONMENT
  CONNECTOR_SERVER_TUNNEL_TOKEN                  required
  CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE       required
  CONNECTOR_SERVER_LISTEN                        default: :8443
  CONNECTOR_SERVER_TLS_CERT                      required unless TLS is in front
  CONNECTOR_SERVER_TLS_KEY                       required unless TLS is in front
  CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS         default: 60
  CONNECTOR_SERVER_REPLAY_CAPACITY               default: 65536
  CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS       default: 30
  CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER      default: 2
  CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE        default: 4
  CONNECTOR_SERVER_MAX_IN_FLIGHT                 default: 64
  CONNECTOR_SERVER_ADMISSION_WAIT_MS             default: 200

EXIT STATUS
  0   The Server stopped after a signal.
  1   Startup failed, or the listener ended with an error.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLE
  CONNECTOR_SERVER_TUNNEL_TOKEN=<secret> \
  CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE=/etc/connector/client-credentials.yaml \
    {{program}} run
`)
}

// CLI returns the help for the cli subcommand.
func CLI(program string) string {
	return replaceProgram(program, `NAME
  {{program}} cli - call one operation on a Node through this Server

SYNOPSIS
  {{program}} cli [FLAGS] OPERATION
  {{program}} cli --help

DESCRIPTION
  Signs one request with a client credential and a node credential, names the Node it
  wants, and prints the result.

  Two credentials are presented on every request, and each is verified by a different
  party:

    client credential   verified by this Server   may this caller use the Server
    node credential     verified by the Node      may this caller use this Node

  Neither credential carries a permission. The Node's own policy file is the only
  place a scope and a permission are granted, so a request for an operation the policy
  does not grant is refused no matter which credential the caller holds.

  The operations are file.list, file.stat and file.read. file.write and command.exec
  are refused in this version.

  This subcommand is the same implementation as the standalone connector-cli binary,
  so either one works. This page lists the flags needed to run a request. The
  standalone binary's help is longer: it adds every error code, the retry advice for
  each one, and the precedence between a flag, an environment variable and a
  configuration file.

FLAGS
  --server URL
        Base URL of the Server, for example http://192.168.2.3:8743.
        Environment: CONNECTOR_CLI_SERVER_URL

  --node-id ID
        The Node the request is for, for example node_ysj64hfylk2ke3aui65fygln2e.
        Environment: CONNECTOR_CLI_NODE_ID

  --client-credential KEY_ID.SECRET
        The credential this Server verifies.
        Environment: CONNECTOR_CLI_CLIENT_CREDENTIAL

  --node-credential KEY_ID.SECRET
        The credential the Node verifies.
        Environment: CONNECTOR_CLI_NODE_CREDENTIAL

  --scope NAME
        The scope name the Node's policy defines, for example project. A scope is a
        name, never a path. Required.
        Environment: CONNECTOR_CLI_SCOPE

  --path PATH
        A path relative to the scope root. Required for file.stat and file.read; use
        an empty value to address the scope root for file.list.
        Environment: CONNECTOR_CLI_PATH

  --offset N, --length N
        Read part of a file. Default 0, which means from the start and to the end.
        Environment: CONNECTOR_CLI_OFFSET, CONNECTOR_CLI_LENGTH

  -o FILE, --output FILE
        Write the content to a file instead of printing it. Refuses an existing file
        unless --force is given.
        Environment: CONNECTOR_CLI_OUTPUT

  --force
        Overwrite an existing -o destination. Without it, an existing file is refused
        rather than replaced, so a mistyped path cannot destroy a file.
        Environment: CONNECTOR_CLI_FORCE

  --json
        Print the whole response envelope instead of just the content.
        Environment: CONNECTOR_CLI_JSON

  --request-id ID
        The request identifier to send, for correlating a call with a Server log. An
        empty value generates one.
        Environment: CONNECTOR_CLI_REQUEST_ID

  -h, --help
        Print this page and exit 0.

  --version
        Print the build this binary came from and exit 0. It is the same build string
        the Server reports, because the cli subcommand is part of this binary.

  CONNECTOR_CLI_ENV_FILE is not a flag. It names a file of KEY=VALUE lines that is
  read before the environment, so one shell can hold several Nodes' settings and a
  command selects one with CONNECTOR_CLI_ENV_FILE=/path/to/file. A value in the
  environment wins over the file, and a flag wins over both.

  The flags come before the operation name. Go's flag parser stops at the first
  word that is not a flag, so an operation written before a flag turns that flag
  into a stray argument and the command fails with a message about arguments rather
  than about order.

EXIT STATUS
  0   The operation succeeded.
  1   The request failed. The message names the error code, for example denied or
      not_found.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLES
  The first three examples assume the four values below are already exported, because
  a request cannot run without them. The last example shows the export itself.

  Read a file:

    {{program}} cli --scope project --path notes.md file.read

  List a scope root, which takes an empty path rather than ".":

    {{program}} cli --scope project --path "" file.list

  Read a file into a local file:

    {{program}} cli --scope project --path big.log -o ./big.log file.read

  Every value can come from the environment instead, so a script can export them
  once:

    CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743 \
    CONNECTOR_CLI_CLIENT_CREDENTIAL=operator.<secret> \
    CONNECTOR_CLI_NODE_ID=node_7f3a...9c1e \
    CONNECTOR_CLI_NODE_CREDENTIAL=caller.<secret> \
      {{program}} cli --scope project --path notes.md file.read
`)
}

// replaceProgram substitutes the program name into a text.
func replaceProgram(program string, text string) string {
	return strings.ReplaceAll(text, programPlaceholder, program)
}
