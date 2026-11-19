// Package nodehelp holds the help text for the connector-node binary.
//
// The text lives in its own package rather than in main for two reasons. The entry
// point stays readable, because a hundred lines of prose between two functions hides
// the control flow. And the text can be tested without starting a process, which is
// what lets a guard test compare it against the source for every environment variable
// and every subcommand.
package nodehelp

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
// precedence between the embedded configuration and the environment, the files the
// Node owns, and every exit status. A help text that lists the subcommands but not the
// variables leaves an operator guessing, and one that names a variable without saying
// which subcommand needs it makes `id` look broken when it refuses a missing dial
// target it never uses.
func Main(program string) string {
	return replaceProgram(program, `NAME
  {{program}} - serve one personal computer to a Connector Server

SYNOPSIS
  {{program}} [run]
  {{program}} id
  {{program}} regenerate
  {{program}} credential add [--key-id NAME]
  {{program}} credential list
  {{program}} credential remove --key-id NAME
  {{program}} help [SUBCOMMAND]
  {{program}} --help
  {{program}} --version

DESCRIPTION
  The Node runs on a personal computer and dials out to the Server. It keeps the
  link open and serves only the operations its local policy allows. It never
  listens, so the machine needs no inbound port, no public address and no firewall
  change.

  The Node is the only authority for permissions. It decides both which area may be
  touched (the scope) and which action may be taken there (the permission). The
  Server holds no scope list and no permission list, so a request the Server has
  already authenticated is still an unauthenticated request as far as this process
  is concerned.

  Three things are generated before the first request, and the order matters
  because each step needs the previous one's output:

    1. the Server's client credential, created with this binary's credential add
    2. this Node's identity, created by id
    3. this Node's credential, created by credential add

  A Node must be started once before anyone can address it, because the Server never
  assigns an identifier.

SUBCOMMANDS
  run
        Start the Node: load the configuration, load the policy, open every scope,
        prepare the identity and the credentials, then dial the Server. This is the
        default, so a bare {{program}} with no subcommand runs it.

        A missing policy file is a startup failure, not an implicit allow-all, so
        the Node refuses to start until the file exists.

  id
        Print this Node's identifier and nothing else, so it can be pasted into a
        script or a ticket. The identifier is created on first use.

        The identifier is an address, not a credential. It appears in the URL and in
        every log line, and knowing it grants nothing without a node credential.

        Reads only CONNECTOR_NODE_CONFIG_DIR. It never dials, so it does not need a
        dial target or a tunnel token, and requiring one would make the first-run
        order impossible.

  regenerate
        Replace the identifier with a fresh one and print it. Every credential is
        left untouched, so a caller does not have to be reissued a secret because the
        Node moved.

        The live channel drops, because it was authenticated under the identity that
        no longer exists. A running Node adopts the new value within one poll
        interval, so a restart is not required.

        Reads only CONNECTOR_NODE_CONFIG_DIR.

  credential add [--key-id NAME]
        Generate a credential and append it to the credential file. The credential is
        printed once, and that is the only moment the secret exists outside the file.

        --key-id names the credential. It is public and may appear in a log or a
        ticket. An empty value generates one.

        Reads only CONNECTOR_NODE_CONFIG_DIR.

  credential list
        Print the public key identifiers, one per line. Never prints a secret: an
        operator who needs the secret has lost it, and the answer is to add a new
        credential rather than to recover the old one.

        Reads only CONNECTOR_NODE_CONFIG_DIR.

  credential remove --key-id NAME
        Remove one credential. The file is rewritten rather than edited in place, so
        a failure leaves the previous set in force instead of a half-written file.

        Removing the last credential is refused. A Node with no credential accepts
        nothing, which looks exactly like a Node whose policy denies everything, and
        an operator who did that by accident would debug the policy instead of the
        credential file.

        Reads only CONNECTOR_NODE_CONFIG_DIR.

  help [SUBCOMMAND]
        Print this help, or the help for one subcommand.

FILES
  The Node owns three files, and they answer three different questions.

    <config>/identity            the node id, and nothing else
                                 written by the Node on first start and on regenerate
                                 answers: which Node is this

    <config>/credentials.yaml    key_id and secret pairs
                                 written by credential add and credential remove
                                 answers: which callers may operate on it

    <config>/policy.yaml         scopes and grants
                                 written by the operator
                                 answers: what may be done, and where

  <config> is CONNECTOR_NODE_CONFIG_DIR when set, otherwise the platform config
  directory joined with topsailai-connector. On Linux that is
  ~/.config/topsailai-connector, on macOS
  ~/Library/Application Support/topsailai-connector, and on Windows
  %AppData%\topsailai-connector.

  The config directory is created with mode 0700 on POSIX, because it holds a
  credential file.

  The identity and the credentials are separate files because they are separate
  things: the identity is an address that may be logged, and a credential is a secret
  that may never be. Merging them would make "change my address" and "revoke a
  caller" the same operation.

ENVIRONMENT
  Every variable carries the CONNECTOR_NODE_ prefix.

  Required by run:

    CONNECTOR_NODE_SERVER_URL
        The Server channel address, for example wss://host/channel. Required.

    CONNECTOR_NODE_TUNNEL_TOKEN
        The secret this Node presents in hello. Required, and an absent or empty
        value is a startup failure rather than a disabled check.

  Read by every subcommand:

    CONNECTOR_NODE_CONFIG_DIR
        Where the identity, the credential file and the policy file live. Defaults to
        the platform config directory joined with topsailai-connector.

  Read by run:

    CONNECTOR_NODE_CREDENTIALS_FILE
        Path to the caller credentials this Node accepts. Defaults to
        <config>/credentials.yaml. A relative path is refused.

    CONNECTOR_NODE_POLICY_FILE
        Path to the policy file. Defaults to <config>/policy.yaml. A missing file is a
        startup failure.

    CONNECTOR_NODE_REPLAY_WINDOW_SECONDS
        How far a node proof timestamp may differ from this machine's clock. Default
        60. At least 1, at most 600.

    CONNECTOR_NODE_REPLAY_CAPACITY
        How many unexpired node nonces are remembered. Default 65536. A full cache
        refuses new proofs rather than evicting a live nonce, because evicting one
        would re-open the replay window it exists to close.

  id, regenerate and the credential subcommands read only
  CONNECTOR_NODE_CONFIG_DIR. They never dial, so they never need a dial target or a
  tunnel token.

  A packaged build may carry a Server URL, a policy and a tunnel token compiled in.
  The environment wins over an embedded value field by field, so an operator can
  repoint one binary without a rebuild. The policy is the deliberate exception: a
  build that embedded a policy refuses CONNECTOR_NODE_POLICY_FILE, because a file
  path would silently replace every scope and every grant.

EXIT STATUS
  0   The subcommand succeeded. A help request also exits 0.
  1   The subcommand failed: a configuration problem, a refused startup, a dial
      failure, or a refused credential operation.
  2   The command line was rejected before anything was done.

  A message beginning "usage:" always accompanies status 2, so a script can tell a
  rejected command line from a failed operation without parsing the text.

EXAMPLES
  Create the identity, then read it:

    {{program}} id

  Create a credential for a caller:

    {{program}} credential add --key-id automation-backup

  List the callers this Node accepts:

    {{program}} credential list

  Revoke one caller:

    {{program}} credential remove --key-id automation-backup

  Change the address without reissuing any secret:

    {{program}} regenerate

  Start the Node:

    CONNECTOR_NODE_TUNNEL_TOKEN=<secret> \
    CONNECTOR_NODE_SERVER_URL=wss://host/channel \
      {{program}} run

  Start it with a policy somewhere else:

    CONNECTOR_NODE_POLICY_FILE=/etc/connector/policy.yaml \
    CONNECTOR_NODE_TUNNEL_TOKEN=<secret> \
    CONNECTOR_NODE_SERVER_URL=wss://host/channel \
      {{program}} run

SEE ALSO
  docs/permission-design.md in the Connector repository describes the three
  credentials, the path fence and the policy file. skills/connector-node-setup/
  describes the same material for a reader who has only the binary.
`)
}

// Run returns the help for the run subcommand.
func Run(program string) string {
	return replaceProgram(program, `NAME
  {{program}} run - dial the Server and serve the operations the policy allows

SYNOPSIS
  {{program}} run
  {{program}}

DESCRIPTION
  Starts the Node. The order of the startup steps is deliberate:

    1. load the configuration, refusing a missing or empty secret
    2. open the runtime, which loads the identity, the credentials and the policy
    3. open one handle per scope the policy defines
    4. dial the Server and keep the link open

  The runtime is opened before the dialer is built, so a Node that cannot serve never
  appears connected. A Node that connected first and then discovered it had nothing to
  serve would look healthy to the Server while refusing every request.

  A generated identity is printed once, at the moment it is created, because the
  operator has to copy it into a CLI and there is no lookup endpoint. A generated
  credential is printed once for the same reason, with a stronger warning: it is a
  secret that never expires.

  The process stops on SIGINT or SIGTERM. The shutdown closes the channel, so a Node
  that is mid-request is answered instead of being cut off.

  A scope whose directory does not exist does not stop startup. The scope stays
  defined, keeps its grant, is reported at WARN with its path, and answers not_found
  until the directory exists and the Node restarts. A policy may name a directory that
  has not been created yet, and on Windows a drive letter may have no volume behind
  it, so one absent directory must not stop a Node that serves several.

  A scope path that exists but is not a directory, a symlink root, a relative path,
  the home directory, a mount point and an existing filesystem root are all startup
  refusals. Only absence is tolerated.

ENVIRONMENT
  CONNECTOR_NODE_SERVER_URL              required
  CONNECTOR_NODE_TUNNEL_TOKEN            required
  CONNECTOR_NODE_CONFIG_DIR              default: platform config directory
  CONNECTOR_NODE_CREDENTIALS_FILE        default: <config>/credentials.yaml
  CONNECTOR_NODE_POLICY_FILE             default: <config>/policy.yaml
  CONNECTOR_NODE_REPLAY_WINDOW_SECONDS   default: 60
  CONNECTOR_NODE_REPLAY_CAPACITY         default: 65536

EXIT STATUS
  0   The Node stopped after a signal.
  1   Startup failed, or the dial loop ended with an error.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLE
  CONNECTOR_NODE_TUNNEL_TOKEN=<secret> \
  CONNECTOR_NODE_SERVER_URL=wss://host/channel \
    {{program}} run
`)
}

// ID returns the help for the id subcommand.
func ID(program string) string {
	return replaceProgram(program, `NAME
  {{program}} id - print this Node's identifier

SYNOPSIS
  {{program}} id

DESCRIPTION
  Prints the node id and nothing else, so the output can be pasted into a script, a
  CLI configuration or a ticket. The identifier is created on first use and then
  reused, so running this twice prints the same value.

  The identifier is an address, not a credential. It appears in the URL and in every
  log line, and knowing it grants nothing without a node credential and a client
  credential.

  Reads only CONNECTOR_NODE_CONFIG_DIR. It never dials, so it does not need a dial
  target or a tunnel token. That is what makes the documented first-run order
  possible: the operator is told to run id before the tunnel token is configured.

ENVIRONMENT
  CONNECTOR_NODE_CONFIG_DIR   default: platform config directory

EXIT STATUS
  0   The identifier was printed.
  1   The identity file could not be read or created.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLE
  {{program}} id
  -> node_7f3a...9c1e
`)
}

// Regenerate returns the help for the regenerate subcommand.
func Regenerate(program string) string {
	return replaceProgram(program, `NAME
  {{program}} regenerate - replace the identifier and print the new one

SYNOPSIS
  {{program}} regenerate

DESCRIPTION
  Writes a fresh node id to the identity file and prints it. Every credential is left
  untouched, so a caller does not have to be reissued a secret because the Node moved.

  This is the point of keeping the address and the secret in separate files. An
  operator who suspects the address has been exposed changes the address without
  reissuing every caller's secret. An operator who suspects a secret has been exposed
  removes that credential instead, which is a different act with a different blast
  radius.

  Two consequences, stated rather than discovered:

    - The live channel drops, because it was authenticated under the identity that no
      longer exists. A channel that survived an identity change would be a channel
      authenticated by a name that no longer exists.
    - A running Node adopts the new value within one poll interval, so a restart is
      not required. "Immediately" therefore means "within one second", not "before
      this command returns".

  Regeneration is local and operator-initiated. The Server cannot trigger it, because
  a Server that could force regeneration could also force a denial of service.

  Reads only CONNECTOR_NODE_CONFIG_DIR.

ENVIRONMENT
  CONNECTOR_NODE_CONFIG_DIR   default: platform config directory

EXIT STATUS
  0   The identifier was replaced and printed.
  1   The identity file could not be rewritten.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLE
  {{program}} regenerate
  -> node_9b2c...4d7f
`)
}

// Credential returns the help for the credential subcommand.
func Credential(program string) string {
	return replaceProgram(program, `NAME
  {{program}} credential - manage the callers this Node accepts

SYNOPSIS
  {{program}} credential add [--key-id NAME]
  {{program}} credential list
  {{program}} credential remove --key-id NAME

DESCRIPTION
  The credential file is the only place a caller is authorized to talk to this Node.
  These commands exist because an operator who must hand-edit a YAML file to add a
  caller will eventually hand-edit it wrong.

  The commands are deliberately small: add one credential, list the public key
  identifiers, remove one. Rotation is add-then-remove, which is the only order that
  does not lock a caller out between two commands.

  A credential is key_id.secret. The key identifier is public and selects one secret
  from the set; the secret is the HMAC key and never leaves the signer and this Node.

  No credential carries a permission. A credential says "you may talk to me"; the
  policy file says "and you may do this".

  Every subcommand reads only CONNECTOR_NODE_CONFIG_DIR.

SUBCOMMANDS
  add [--key-id NAME]
        Generate a credential and append it to the file. The credential is printed
        once, and that is the only moment the secret exists outside the file. Copy it
        into the CLI before the output is lost, and do not paste it into a ticket, a
        chat message or a shell history that is retained.

        --key-id names the credential. It is public, so it may appear in a log or a
        ticket. An empty value generates one.

  list
        Print the public key identifiers, one per line. Never prints a secret. An
        operator who needs the secret has lost it, and the answer is to add a new
        credential rather than to recover the old one: a file that could print a
        secret is a file that can leak one.

  remove --key-id NAME
        Remove one credential. The file is rewritten rather than edited in place, so a
        failure leaves the previous set in force instead of a half-written file.

        Removing the last credential is refused. A Node with no credential accepts
        nothing, which looks exactly like a Node whose policy denies everything, and an
        operator who did that by accident would debug the policy instead of the
        credential file.

ENVIRONMENT
  CONNECTOR_NODE_CONFIG_DIR   default: platform config directory

EXIT STATUS
  0   The operation succeeded.
  1   The credential file could not be read or written, or the named credential does
      not exist, or it is the last one.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLES
  {{program}} credential add --key-id automation-backup
  -> automation-backup.q4ka...

  {{program}} credential list
  -> automation-backup

  {{program}} credential remove --key-id automation-backup
`)
}

// replaceProgram substitutes the program name into a text.
func replaceProgram(program string, text string) string {
	return strings.ReplaceAll(text, programPlaceholder, program)
}
