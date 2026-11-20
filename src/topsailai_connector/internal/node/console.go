package node

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log/slog"
	"strings"

	"topsailai_connector/internal/security"
)

// maxConsoleLineBytes bounds one console line.
//
// The limit exists for the same reason the path grammar has one: an unbounded line is a
// memory problem, and a scanner that silently truncates a long line would execute a
// command the operator did not type.
const maxConsoleLineBytes = 64 << 10

// Console is the interactive control surface of a running Node.
//
// It exists because a stateless Node has no file to edit. `connector-node regenerate`
// and the three `credential` subcommands all work by rewriting the identity file and the
// credential file, so on a Node that writes nothing they have nothing to act on. The
// console changes the same two values in memory, through the same holder the dispatcher
// and the dialer read, so a change takes effect without a restart and without a file.
//
// The console is not a second authority. It cannot add a scope, widen a grant or change
// the policy: those live in the policy document, which is loaded once at startup and
// reloaded only from a file. It can change exactly the three things the file-backed
// subcommands and the environment can change, which are who the Node is, who may talk
// to it, and which Server it dials.
//
// It works in both modes. On a file-backed Node a change is also written to the file, so
// the console and `connector-node regenerate` agree about what is in force; on a
// stateless Node the change lives in memory and is lost when the process exits, which is
// the same lifetime the identity and the credentials already have in that mode.
type Console struct {
	runtime *Runtime
	out     io.Writer
	// requestIdentityChange asks the dialer to drop the live channel. It is a function
	// rather than a dialer reference so a console can be built for a Node that never
	// dials, and so a test can observe the request without a running dialer.
	requestIdentityChange func()
	// setServerURL hands a validated address to the dialer. It is a function for the
	// same reason requestIdentityChange is one: the console is built before the dialer
	// exists, and a console built for a Node that never dials has nothing to hand the
	// value to.
	setServerURL func(string)
	// requestReconnect asks the dialer to drop the live channel because the Server
	// address changed. It is a separate function from requestIdentityChange because the
	// two events write different log lines: a repoint reported as an identity change
	// sends an operator looking for a regeneration that never happened.
	requestReconnect func()
	logger           *slog.Logger
	// logLevel is the switch behind the `log` command. It is the same LevelVar the
	// process logger was built from, so changing it here changes what every component
	// writes, not only what the console writes.
	//
	// It is a pointer rather than a value because a slog.LevelVar is the only way to
	// change a handler's level after the handler is built. A console that rebuilt the
	// logger would leave the dispatcher and the dialer holding the old one.
	logLevel *slog.LevelVar

	// Prompt is written before each read. An empty value writes nothing, which is what a
	// caller that redirected stdout wants: a prompt in a log file is noise that reads
	// like output.
	Prompt string
}

// NewConsole returns a console driving the given runtime.
//
// A nil output discards everything, and a nil logger falls back to the default logger.
// Neither is substituted with a guess about what the caller meant, because a console
// that invented an output stream would print a secret somewhere nobody expected.
//
// A nil level disables the `log` command rather than inventing a switch: a console that
// reported a level it could not change would be a console that lies about what the
// process is doing.
func NewConsole(runtime *Runtime, out io.Writer, requestIdentityChange func(), logger *slog.Logger) *Console {
	if out == nil {
		out = io.Discard
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Console{
		runtime:               runtime,
		out:                   out,
		requestIdentityChange: requestIdentityChange,
		logger:                logger,
	}
}

// SetLogLevel installs the switch behind the `log` command.
//
// It is a setter for the same reason SetIdentityChangeRequest is one: the console is
// built before the logger's level is known to the caller that owns it, and a console
// built by a test has no process logger at all.
func (c *Console) SetLogLevel(level *slog.LevelVar) {
	c.logLevel = level
}

// SetIdentityChangeRequest installs the function that asks the dialer to drop the
// live channel.
//
// It exists because the console is built before the dialer. The dialer is created
// inside the serving function, after the console has been decided, so the callback
// cannot be passed to NewConsole: at that moment there is no dialer to ask. A setter
// keeps the construction order natural and keeps the console constructible for a
// Node that never dials.
//
// A nil value is accepted and means "no dialer to ask", which is the correct state
// for a console built by a test or for a Node that serves without a channel. The
// console still changes the identity in memory in that case; only the channel drop
// is skipped, and the next dial uses the new identity because the dialer reads the
// holder.
func (c *Console) SetIdentityChangeRequest(request func()) {
	c.requestIdentityChange = request
}

// SetServerURLSetter installs the function that hands a validated address to the
// dialer.
//
// It exists for the same reason SetIdentityChangeRequest does: the dialer is created
// after the console, so the callback cannot be passed to NewConsole. A nil value is
// accepted and means "no dialer to tell", which is the correct state for a console
// built by a test or for a Node that serves without a channel; the address is still
// changed in memory, so `server` and `show config` agree afterwards.
func (c *Console) SetServerURLSetter(set func(string)) {
	c.setServerURL = set
}

// SetReconnectRequest installs the function that asks the dialer to drop the live
// channel because the Server address changed.
//
// It is separate from SetIdentityChangeRequest for the same reason the dialer has two
// methods: the log line names which event happened, and one callback for both events
// would report a repoint as a regeneration. A nil value is accepted and means "no
// dialer to ask", which is the correct state for a console built by a test.
func (c *Console) SetReconnectRequest(request func()) {
	c.requestReconnect = request
}

// Run reads commands until the input ends, the context is cancelled or `quit` is typed.
//
// A command that fails prints its error and the loop continues, because a console that
// exited on a typo would be a console the operator has to restart the Node to get back.
// Only `quit` and the end of the input end the loop.
//
// A read that is already blocked when the context is cancelled is not interrupted: the
// standard library has no portable way to cancel a read on a terminal, and closing the
// process's own stdin would be a side effect on a descriptor the caller owns. The
// goroutine therefore ends with the process, which is what happens on shutdown anyway.
func (c *Console) Run(ctx context.Context, input io.Reader) error {
	if input == nil {
		return fmt.Errorf("console input is nil")
	}

	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 0, 4096), maxConsoleLineBytes)

	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		if c.Prompt != "" {
			fmt.Fprint(c.out, c.Prompt)
		}
		if !scanner.Scan() {
			return scanner.Err()
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		quit, err := c.execute(line)
		if err != nil {
			fmt.Fprintf(c.out, "error: %v\n", err)
			continue
		}
		if quit {
			return nil
		}
	}
}

// execute runs one command line and reports whether it asked to quit.
func (c *Console) execute(line string) (bool, error) {
	fields := strings.Fields(line)
	switch fields[0] {
	case "help", "?":
		c.printHelp()
		return false, nil
	case "show":
		return false, c.show(fields[1:])
	case "regenerate":
		return false, c.regenerate(fields[1:])
	case "credential":
		return false, c.credential(fields[1:])
	case "log":
		return false, c.log(fields[1:])
	case "server":
		return false, c.server(fields[1:])
	case "quit", "exit":
		// The console stops reading but the Node keeps serving, so the operator needs
		// to be told which of the two happened. A silent exit reads as a hang.
		fmt.Fprintln(c.out, "console closed; the node keeps running")
		return true, nil
	default:
		return false, fmt.Errorf("unknown command %q; type help for the list", fields[0])
	}
}

// log reports or changes the level the process logger writes at.
//
// The command exists because the console and the log share one terminal. A Node that
// retries a refused dial every five seconds writes a warning every five seconds, and
// that warning lands in the middle of whatever the operator is typing. Turning the log
// down is the smallest fix that needs no line editor and no third-party dependency.
//
// It changes the process logger's level rather than the console's own output, because
// the noise comes from the dialer and the dispatcher, not from the console. A switch
// that silenced only the console would silence nothing the operator complained about.
//
// The level is a slog.LevelVar, so the change reaches every component that was handed
// the logger at startup. Rebuilding the logger would leave those components holding the
// old one, which is the defect this command would have if it were written the obvious
// way.
func (c *Console) log(args []string) error {
	if c.logLevel == nil {
		return fmt.Errorf("this console has no log switch; the process logger was built without one")
	}
	if len(args) == 0 {
		fmt.Fprintf(c.out, "log level: %s\n", levelName(c.logLevel.Level()))
		return nil
	}
	if len(args) != 1 {
		return fmt.Errorf("usage: log [debug|info|warn|error|off]")
	}

	level, ok := parseLevel(args[0])
	if !ok {
		return fmt.Errorf("unknown level %q; want debug, info, warn, error or off", args[0])
	}
	c.logLevel.Set(level)
	fmt.Fprintf(c.out, "log level: %s\n", levelName(level))
	if level == levelOff {
		fmt.Fprintln(c.out, "the log is off; a failure is still reported when the node exits")
	}
	return nil
}

// levelOff is the level above error, so a handler at this level writes nothing.
//
// slog has no "off" constant, and a level above every real one is the documented way to
// silence a handler. It is named here rather than written as a bare number so the
// console's help and the code agree about what "off" means.
const levelOff = slog.LevelError + 4

// parseLevel maps a console word to a slog level.
func parseLevel(word string) (slog.Level, bool) {
	switch word {
	case "debug":
		return slog.LevelDebug, true
	case "info":
		return slog.LevelInfo, true
	case "warn", "warning":
		return slog.LevelWarn, true
	case "error":
		return slog.LevelError, true
	case "off", "none", "quiet":
		return levelOff, true
	default:
		return 0, false
	}
}

// levelName maps a slog level back to the word the console accepts.
//
// A level that is not one of the five named ones is reported by its number rather than
// rounded to the nearest name, because a console that reported "info" for a level it
// never set would be a console that misreports the state it exists to report.
func levelName(level slog.Level) string {
	switch level {
	case slog.LevelDebug:
		return "debug"
	case slog.LevelInfo:
		return "info"
	case slog.LevelWarn:
		return "warn"
	case slog.LevelError:
		return "error"
	case levelOff:
		return "off"
	default:
		return fmt.Sprintf("custom (%d)", int(level))
	}
}

// show prints one piece of the Node's state.
//
// Every command here is read-only, so none of them can change what the Node serves. The
// credential listing prints the public key identifiers and never a secret, because a
// secret that reaches a terminal is a secret in a scrollback buffer.
func (c *Console) show(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("usage: show config|identity|credentials|scopes|status")
	}

	switch args[0] {
	case "config":
		c.showConfig()
	case "identity":
		fmt.Fprintf(c.out, "node id: %s\n", c.runtime.IdentityID())
	case "credentials":
		keyIDs := c.runtime.IdentityHolder().Credentials().KeyIDs()
		if len(keyIDs) == 0 {
			fmt.Fprintln(c.out, "no credential is in force; this node accepts nothing")
			return nil
		}
		for _, keyID := range keyIDs {
			fmt.Fprintf(c.out, "key id: %s\n", keyID)
		}
	case "scopes":
		c.showScopes()
	case "status":
		c.showStatus()
	default:
		return fmt.Errorf("unknown subject %q; want config, identity, credentials, scopes or status", args[0])
	}
	return nil
}

// showConfig prints the configuration in force, one field per line.
//
// One field per line rather than the single line the log writes, because the two have
// different readers. A log line is grepped and wants to be one record; a console answer
// is read by a person on a terminal of unknown width, and a single line wraps in the
// middle of a value. The measured case was `config_dir=stateless` broken across two
// lines as `stat` and `eless`, which reads as a different value.
//
// The tunnel token is redacted by Secret.Redacted, which reports the length and never a
// prefix. A console answer is the most likely thing to be pasted into a ticket, so it
// must not carry a secret even when the operator would find it convenient.
func (c *Console) showConfig() {
	config := c.runtime.Config()

	policy := config.PolicyPath
	if config.PolicyBytes != nil {
		policy = "embedded in this binary"
	}
	configDir := config.ConfigDir
	credentials := config.CredentialsPath
	if config.Stateless {
		configDir = "stateless (nothing is written)"
		credentials = "stateless (nothing is written)"
	}

	fmt.Fprintf(c.out, "server: %s\n", config.ServerURL)
	fmt.Fprintf(c.out, "tunnel token: %s\n", config.TunnelToken.Redacted())
	fmt.Fprintf(c.out, "config dir: %s\n", configDir)
	fmt.Fprintf(c.out, "credentials: %s\n", credentials)
	fmt.Fprintf(c.out, "policy: %s\n", policy)
	fmt.Fprintf(c.out, "replay window: %s\n", config.ReplayWindow)
	fmt.Fprintf(c.out, "replay capacity: %d\n", config.ReplayCapacity)
}

// showScopes prints every scope and whether its directory exists.
//
// The absent marker is the same fact the startup warning carries, and it is repeated
// here because an operator who started the Node hours ago no longer has that line in
// front of them.
func (c *Console) showScopes() {
	names := c.runtime.Authority().ScopeNames()
	if len(names) == 0 {
		fmt.Fprintln(c.out, "no scope is defined; this node serves nothing")
		return
	}
	for _, name := range names {
		scope, ok := c.runtime.Authority().Scope(name)
		if !ok {
			fmt.Fprintf(c.out, "scope: %s\n", string(name))
			continue
		}
		state := "present"
		if scope.Absent() {
			state = "absent; every request answers not_found until the directory exists and the node restarts"
		}
		fmt.Fprintf(c.out, "scope: %s (%s)\n", string(name), state)
	}
}

// showStatus prints the one-line answer to "what is this Node doing".
func (c *Console) showStatus() {
	config := c.runtime.Config()
	mode := "file-backed"
	if config.Stateless {
		mode = "stateless; nothing is written and the identity is lost when this process exits"
	}
	fmt.Fprintf(c.out, "mode: %s\n", mode)
	fmt.Fprintf(c.out, "node id: %s\n", c.runtime.IdentityID())
	fmt.Fprintf(c.out, "server: %s\n", config.ServerURL)
	fmt.Fprintf(c.out, "scopes: %d\n", len(c.runtime.Authority().ScopeNames()))
	fmt.Fprintf(c.out, "credentials: %d\n", c.runtime.IdentityHolder().Credentials().Len())
}

// server reports or replaces the Server address.
//
// It exists because a Node packaged against the wrong address had no way to be
// corrected without a rebuild and a restart. The address is one value, it is not a
// secret, and it is the only setting besides the identity and the credentials that the
// console can change.
//
// The tunnel token is deliberately not changeable here. It is one value like the
// address, but it is a secret, and a secret typed at a terminal is a secret in a
// scrollback buffer. A Node moved to a Server with a different token is refused at the
// handshake, which is a visible failure rather than a silent one.
//
// The value is validated by the same function the startup path uses, so the console
// cannot accept an address that `run` would refuse. A refusal leaves the address in
// force unchanged, and the message names the reason rather than repeating a usage line.
func (c *Console) server(args []string) error {
	if len(args) == 0 {
		fmt.Fprintf(c.out, "server: %s\n", c.runtime.ServerURL())
		return nil
	}
	if len(args) > 1 {
		return fmt.Errorf("usage: server [address]; unexpected argument %q", args[1])
	}

	address := args[0]
	previous, err := c.runtime.ReplaceServerURL(address)
	if err != nil {
		// The startup validator names the variable, which is the right name in a
		// startup message and the wrong one here: the operator typed an address at a
		// console, not a variable into an environment. The reason is kept and the
		// variable name is dropped, so the message names what the operator can act on.
		return fmt.Errorf("the address %q is not usable: %s", address, strings.ReplaceAll(err.Error(), "CONNECTOR_NODE_SERVER_URL ", ""))
	}

	if c.setServerURL != nil {
		c.setServerURL(address)
	}
	fmt.Fprintf(c.out, "server: %s\n", address)
	if previous == address {
		fmt.Fprintln(c.out, "the address is unchanged; the live channel is kept")
		return nil
	}
	fmt.Fprintln(c.out, "the live channel is dropped and the node dials the new address")
	// The change is not persisted, and saying so is the difference between a change
	// that reverted and a change that never happened. The Node has no configuration
	// file of its own, so there is nowhere to write it.
	fmt.Fprintln(c.out, "this is not remembered across a restart; the address this process started with is used again")
	if c.requestReconnect != nil {
		c.requestReconnect()
	}
	return nil
}

// regenerate replaces the node id.
//
// The credential is deliberately untouched, which is the same contract
// `connector-node regenerate` has: an exposed address is changed without reissuing every
// caller's secret. The live channel is dropped because it was authenticated under the
// retired identity, so a connection cannot survive the name that authenticated it.
func (c *Console) regenerate(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: regenerate id")
	}
	if len(args) > 1 {
		return fmt.Errorf("usage: regenerate id; unexpected argument %q", args[1])
	}
	if args[0] != "id" {
		return fmt.Errorf("unknown subject %q; regenerate changes the node id, so the only subject is id", args[0])
	}

	nodeID, err := security.NewNodeID()
	if err != nil {
		return fmt.Errorf("generate a node id: %w", err)
	}
	changed, err := c.runtime.ReplaceNodeID(nodeID)
	if err != nil {
		return err
	}
	if !changed {
		return nil
	}

	fmt.Fprintf(c.out, "node id: %s\n", nodeID)
	fmt.Fprintln(c.out, "the live channel is dropped; every credential is unchanged")
	if c.requestIdentityChange != nil {
		c.requestIdentityChange()
	}
	return nil
}

// credential adds, rotates or removes one credential.
//
// A rotation keeps the key identifier and replaces the secret, which is the operation
// the file-backed path cannot express without editing the file by hand. It is a
// separate verb from `add` because the two have different blast radii: `add` leaves the
// existing caller working, while `rotate` breaks it until it is given the new secret.
func (c *Console) credential(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: credential add|rotate|remove <key-id>; to see the key ids, use show credentials")
	}
	action := args[0]
	if action == "list" || action == "show" {
		// The natural word for "show me the credentials" is list, and the answer is a
		// different command. Naming it here is cheaper than letting the operator
		// conclude the feature does not exist.
		return fmt.Errorf("there is no credential %s; use show credentials to see the key ids", action)
	}
	if len(args) != 2 {
		return fmt.Errorf("usage: credential %s <key-id>", action)
	}
	keyID := args[1]

	list, err := c.runtime.CredentialList()
	if err != nil {
		return err
	}

	switch action {
	case "add":
		return c.addCredential(list, keyID)
	case "rotate":
		return c.rotateCredential(list, keyID)
	case "remove":
		return c.removeCredential(list, keyID)
	default:
		return fmt.Errorf("unknown action %q; want add, rotate or remove", action)
	}
}

// addCredential appends a new credential and prints its secret once.
func (c *Console) addCredential(list []security.Credential, keyID string) error {
	if _, found := findCredential(list, keyID); found {
		return fmt.Errorf("the key id %q already exists; use credential rotate to replace its secret", keyID)
	}

	created, err := security.NewCredentialWithKeyID(keyID)
	if err != nil {
		return err
	}
	updated := append(append([]security.Credential{}, list...), created)
	if err := c.runtime.ReplaceCredentials(updated); err != nil {
		return err
	}

	fmt.Fprintf(c.out, "credential: %s.%s\n", created.KeyID, created.Secret)
	fmt.Fprintln(c.out, "copy it now; it is not printed again")
	return nil
}

// rotateCredential replaces the secret under an existing key id.
func (c *Console) rotateCredential(list []security.Credential, keyID string) error {
	index, found := findCredential(list, keyID)
	if !found {
		return fmt.Errorf("no credential has the key id %q; use credential add to create one", keyID)
	}

	created, err := security.NewCredentialWithKeyID(keyID)
	if err != nil {
		return err
	}
	updated := append([]security.Credential{}, list...)
	updated[index] = created
	if err := c.runtime.ReplaceCredentials(updated); err != nil {
		return err
	}

	fmt.Fprintf(c.out, "credential: %s.%s\n", created.KeyID, created.Secret)
	fmt.Fprintln(c.out, "the previous secret for this key id no longer authenticates; copy the new one now")
	return nil
}

// removeCredential revokes one credential.
//
// The last credential cannot be removed, for the same reason the file-backed command
// refuses it: a Node with no credential accepts nothing, and the operator would have no
// way back in without restarting with a different configuration.
func (c *Console) removeCredential(list []security.Credential, keyID string) error {
	index, found := findCredential(list, keyID)
	if !found {
		return fmt.Errorf("no credential has the key id %q", keyID)
	}
	if len(list) == 1 {
		return fmt.Errorf("refusing to remove the last credential; a node with no credential accepts nothing")
	}

	updated := append([]security.Credential{}, list[:index]...)
	updated = append(updated, list[index+1:]...)
	if err := c.runtime.ReplaceCredentials(updated); err != nil {
		return err
	}

	fmt.Fprintf(c.out, "removed: %s\n", keyID)
	return nil
}

// findCredential returns the index of the credential with the given key id.
func findCredential(list []security.Credential, keyID string) (int, bool) {
	for index := range list {
		if list[index].KeyID == keyID {
			return index, true
		}
	}
	return 0, false
}

// printHelp lists the commands.
//
// The list is written out rather than generated from a table, because a table that
// generated both the help and the dispatch would let a command exist that the help never
// mentions, and the help is the only documentation a console user has.
func (c *Console) printHelp() {
	fmt.Fprint(c.out, `commands:
  show config        the configuration in force, with the tunnel token redacted
  show identity      the node id this node answers to
  show credentials   the public key ids; a secret is never printed
  show scopes        every scope and whether its directory exists
  show status        the mode, the node id, the server and the counts
  log [level]        show or set the log level: debug, info, warn, error or off
  server [address]   show the Server address, or dial a different Server
  regenerate id      replace the node id; every credential is unchanged
  credential add <key-id>     add a caller and print its secret once
  credential rotate <key-id>  replace the secret under an existing key id
  credential remove <key-id>  revoke one caller; the last one cannot be removed
  help               this list
  quit               stop reading commands; the node keeps running
`)
}
