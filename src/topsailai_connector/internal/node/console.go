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
// reloaded only from a file. It can change exactly the two things the file-backed
// subcommands can change, which are who the Node is and who may talk to it.
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
	logger                *slog.Logger

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
	case "quit", "exit":
		return true, nil
	default:
		return false, fmt.Errorf("unknown command %q; type help for the list", fields[0])
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
		fmt.Fprintf(c.out, "%s\n", c.runtime.Config().Redacted())
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

// regenerate replaces the node id.
//
// The credential is deliberately untouched, which is the same contract
// `connector-node regenerate` has: an exposed address is changed without reissuing every
// caller's secret. The live channel is dropped because it was authenticated under the
// retired identity, so a connection cannot survive the name that authenticated it.
func (c *Console) regenerate(args []string) error {
	if len(args) != 1 || args[0] != "id" {
		return fmt.Errorf("usage: regenerate id")
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
	if len(args) != 2 {
		return fmt.Errorf("usage: credential add|rotate|remove <key-id>")
	}
	action, keyID := args[0], args[1]

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
  regenerate id      replace the node id; every credential is unchanged
  credential add <key-id>     add a caller and print its secret once
  credential rotate <key-id>  replace the secret under an existing key id
  credential remove <key-id>  revoke one caller; the last one cannot be removed
  help               this list
  quit               stop reading commands; the node keeps running
`)
}
