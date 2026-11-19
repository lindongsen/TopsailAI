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
  {{program}} scope list
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

        Every start prints a summary to stdout: the Server address, the node id, the
        config directory, the credential and policy paths, the scope names, the key
        id and the secret, followed by the CONNECTOR_CLI_* variables a caller needs.
        A first start also says that it generated the node id and the credential.

        The secret is printed in full only when stdout is a terminal. When stdout is
        redirected the summary still appears, with the secret replaced by
        <secret:N bytes> and a line saying why, so a launcher that logs stdout does
        not append a credential that never expires to that log on every start. Run
        the Node in a terminal to see the secret, or read the credentials file named
        on the credentials line.

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

  scope list
        Print the scope names the policy defines, one per line, in sorted order.

        Every CLI request carries a scope name, and a caller cannot ask this Node for
        the list: the Node answers "denied" for a scope the policy does not define
        and for a scope without a grant alike, so an answer that distinguished them
        would let anyone enumerate the scopes on a machine they have no permission
        on. The names come from the machine that defines them, which is this one.

        Names are printed, never paths. A name is public and already appears in the
        startup log; a path is this machine's filesystem layout.

        Reads CONNECTOR_NODE_CONFIG_DIR and CONNECTOR_NODE_POLICY_FILE. It never
        dials and never opens a scope, so it works before the first start and on a
        machine where a scope directory has not been created yet.

  help [SUBCOMMAND]
        Print this help, or the help for one subcommand.

FILES
  The Node owns three files, and they answer three different questions.

    <config>/identity            the node id, and nothing else
                                 written by the Node on first start and on regenerate
                                 answers: which Node is this

    <config>/credentials.yaml    key_id and secret pairs
                                 written by credential add, credential remove, and by
                                 the first run when the file does not exist yet
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

POLICY FILE
  The policy file is the only place a scope and a permission are granted. It is
  required: a missing file is a startup failure, and an empty file is refused
  rather than read as an empty policy. This is the whole format:

    version: 1
    scopes:
      project:
        path: /home/me/project
      scratch:
        path: /home/me/scratch
    grants:
      - scope: project
        permissions: [read, list, stat]
      - scope: scratch
        permissions: [read, list, stat]

  version is required and must be 1.

  scopes maps a name to a directory. The name is what a caller asks for, so it is
  never a path: letters, digits, "-" and "_" only. The path must be absolute, and
  it must not be the home directory, a filesystem root, a symlink, a mount point,
  or a directory that contains this Node's config directory. A path that does not
  exist yet is accepted, and that scope answers not_found until the directory
  exists and the Node restarts.

  grants says which permissions each scope allows. The permission names are read,
  list and stat. A grant naming a scope that scopes does not define is refused, so
  a typo fails startup instead of looking like a working policy.

  write and exec are accepted by the parser but do nothing in this version:
  file.write and command.exec are refused before the policy is consulted. A grant
  that lists them starts the Node and grants nothing, so do not add them expecting
  them to work.

  An unknown key anywhere in the file is refused rather than ignored, because a
  typo in a security file that is silently skipped is worse than a crash. The file
  is capped at 1 MiB.

  To check a policy without starting the Node, run it and read stderr: a policy that
  is accepted logs "connector-node starting" and then "connector-node ready", and a
  rejected one prints "load authority:" followed by the reason and exits 1. The
  startup log goes to stderr, so a check that reads stdout sees only the node id and
  the generated credential.

ENVIRONMENT
  Every variable carries the CONNECTOR_NODE_ prefix.

  Required by run:

    CONNECTOR_NODE_SERVER_URL
        The Server channel address, for example wss://host/channel. Required.

    CONNECTOR_NODE_TUNNEL_TOKEN
        The secret this Node presents in hello. Required, and an absent or empty
        value is a startup failure rather than a disabled check. At least 16 bytes,
        and a shorter value is refused at startup with the length it received, so a
        placeholder such as "test" fails before the Node dials.

  Read by every subcommand:

    CONNECTOR_NODE_CONFIG_DIR
        Where the identity, the credential file and the policy file live. Defaults to
        the platform config directory joined with topsailai-connector. Must be an
        absolute path; a relative one is refused, because it would resolve differently
        depending on the directory the Node was started from.

  Read by run:

    CONNECTOR_NODE_CREDENTIALS_FILE
        Path to the caller credentials this Node accepts. Defaults to
        <config>/credentials.yaml. A relative path is refused.

    CONNECTOR_NODE_POLICY_FILE
        Path to the policy file. Defaults to <config>/policy.yaml. A missing file is a
        startup failure, and so is a relative path.

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
  {{program}} help run, help id, help regenerate, help credential
        The page for one subcommand.

  {{program}} --version
        The build this binary came from, which is what to quote in a bug report.

  The Server side of the same system is connector-server. The caller side is
  connector-cli, or connector-server cli if only the Server binary is installed.
  Both are separate programs, so this binary's help cannot describe them.
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

  Every start prints a summary of what this Node is and how to reach it: the Server
  address, the node id, the config directory, the policy source, the scopes, the key
  id and the credential, followed by the CONNECTOR_CLI_* variables a CLI needs. It is
  printed on every start rather than only the first, because an operator who restarts
  a Node has the same question as one who started it.

  The secret appears in full only when stdout is a terminal. When stdout is redirected
  to a file or a pipe the summary still prints, with the secret replaced by its
  redacted form and a line saying why. A launcher that writes stdout to a log would
  otherwise append a credential that never expires to that log on every start.

  A generated identity and a generated credential are announced above the summary, so
  an operator can tell a first start from a restart. The values themselves are in the
  summary either way.

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

// Scope is the help page for the scope subcommand.
//
// It is written for the operator who owns the policy file and cannot remember which
// scope names they wrote. The page states the one thing that makes the command
// necessary: a caller cannot ask the Node, because the Node answers `denied` for an
// undefined scope and for a scope without a grant alike, so the names have to come
// from the machine that defines them.
func Scope(program string) string {
	return replaceProgram(program, `NAME
  {{program}} scope - show the scope names this Node's policy defines

SYNOPSIS
  {{program}} scope list

DESCRIPTION
  Every CLI request carries a scope name, and the name must be one the policy
  defines. Without this command the only way to learn a name is to open the policy
  file or read a log line, which is why it exists.

  A caller cannot ask the Node. The Node answers "denied" for a scope the policy
  does not define and for a scope without a grant alike, so a caller cannot probe
  for names: an answer that distinguished the two would let anyone enumerate the
  scopes on a machine they have no permission on. The names therefore come from the
  machine that defines them, which is this one.

  The names are read from the policy document, which is the only place a scope is
  defined. The answer is exactly the set the Node would serve, not a second list
  that could drift from it.

  Names are printed, never paths. A scope name is public and already appears in the
  Node's startup log. A scope path is this machine's filesystem layout, which the
  design keeps off the wire and out of the Server's knowledge.

  The command does not dial the Server, does not need the tunnel token and does not
  open a scope, so it works before the first start and on a machine where a scope
  directory has not been created yet.

SUBCOMMANDS
  list
        Print the scope names the policy defines, one per line, in sorted order.

        A policy that defines no scope prints nothing and exits 0. That is an empty
        policy, which refuses every request, and it is a valid document rather than
        an error.

ENVIRONMENT
  CONNECTOR_NODE_CONFIG_DIR    default: platform config directory
  CONNECTOR_NODE_POLICY_FILE   default: CONNECTOR_NODE_CONFIG_DIR/policy.yaml

  Both must be absolute when set. A relative path resolves differently per launch,
  so it is refused rather than resolved.

  A build that compiled its policy in refuses CONNECTOR_NODE_POLICY_FILE, because
  the two would disagree about every scope and every grant. Such a build lists the
  scopes it carries.

EXIT STATUS
  0   The names were printed. An empty policy prints nothing and still exits 0.
  1   The policy file could not be read, or it is malformed, or the config directory
      could not be resolved.
  2   The command line was rejected. The message begins "usage:", so a script can
      tell a rejected command line from a failed operation without parsing the text.

EXAMPLES
  {{program}} scope list
  -> project
     tool

  Then use one of those names on a request:
  connector-server cli --scope project --path notes.md file.read
`)
}

// replaceProgram substitutes the program name into a text.
func replaceProgram(program string, text string) string {
	return strings.ReplaceAll(text, programPlaceholder, program)
}
