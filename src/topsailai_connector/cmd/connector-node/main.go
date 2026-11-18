// Command connector-node is the personal-computer entry point. It dials the Server,
// keeps the link open and serves the operations its policy allows.
//
// The process loads the configuration, loads the policy, opens every scope the policy
// defines, prepares the node identity and its credentials, and then dials the Server.
// It never listens: the Node is the side that initiates, so a personal computer needs
// no inbound port, no public address and no firewall change.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "connector-node: %v\n", err)
		os.Exit(1)
	}
}

// run is the whole process, separated from main so a test can call it and so every
// failure returns an error instead of calling os.Exit in the middle.
func run(arguments []string) error {
	command, rest := splitCommand(arguments)

	switch command {
	case "", "run":
		return runNode(rest)
	case "id":
		return runID(rest)
	case "regenerate":
		return runRegenerate(rest)
	case "credential":
		return runCredential(rest)
	default:
		return fmt.Errorf("unknown command %q; want run, id, regenerate or credential", command)
	}
}

// splitCommand separates the subcommand from its flags.
//
// A leading flag means the default subcommand, so `connector-node --help` works without
// naming `run`. A leading word that is not a known command is returned as the command,
// so `run` reports it as unknown instead of starting the Node: a typo that silently
// starts the default subcommand is a typo an operator never learns about.
func splitCommand(arguments []string) (string, []string) {
	if len(arguments) == 0 {
		return "", nil
	}
	switch arguments[0] {
	case "run", "id", "regenerate", "credential":
		return arguments[0], arguments[1:]
	}
	if strings.HasPrefix(arguments[0], "-") {
		return "", arguments
	}
	return arguments[0], arguments[1:]
}

// rejectStrayArguments refuses a positional argument that no flag consumed.
//
// flag.Parse accepts a positional argument and leaves it in Args(), so a word that is
// not a flag is silently dropped by a caller that never checks. That is how
// `connector-node run serve` used to start the Node: `serve` was parsed as a positional
// argument, ignored, and the default subcommand ran. A word the operator typed must
// either be a flag or be refused, because a silently ignored word is a typo the operator
// never learns about.
func rejectStrayArguments(flags *flag.FlagSet) error {
	if flags.NArg() == 0 {
		return nil
	}
	return fmt.Errorf("unexpected argument %q; want flags only", flags.Arg(0))
}

// runNode starts the Node: configuration, identity, credentials, policy, scopes, then
// dial.
//
// The order is deliberate. The runtime is opened first, because it loads the identity,
// the credentials and the policy and refuses to start when any of them is unusable; a
// dialer built before that would connect to the Server and then discover it has nothing
// to serve. The dialer is built last, so a Node that cannot serve never appears
// connected.
func runNode(arguments []string) error {
	// The signal channel is created here rather than inside runNodeWithSignals, so the
	// whole process can be tested without sending a signal to the test binary.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	return runNodeWithSignals(arguments, signals)
}

// runNodeWithSignals is runNode with the signal channel supplied by the caller.
//
// The channel is a parameter so a test can drive the complete process, including the
// dial, without signalling the test binary: a real signal would make the test depend on
// the order in which two handlers register, and a mistake there would kill the test
// binary instead of failing the test.
func runNodeWithSignals(arguments []string, signals <-chan os.Signal) error {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))

	config, err := node.LoadConfig(os.Getenv)
	if err != nil {
		return err
	}

	runtime, err := node.Open(config, logger)
	if err != nil {
		return err
	}
	defer runtime.Close()

	logger.Info("connector-node starting", "protocol", protocol.Version)

	// A generated identifier is printed once, at the moment it is created, because the
	// operator has to copy it into a CLI and there is no lookup endpoint. It goes to
	// stdout rather than to the log, so a log file does not accumulate addresses.
	nodeID, generated := runtime.NewIdentity()
	if generated {
		fmt.Printf("node id generated: %s\n", nodeID)
	}

	// A generated credential is printed once, for the same reason and with a stronger
	// warning: it is a secret that never expires, so the operator must copy it into the
	// CLI and must not paste it into a ticket or a retained shell history.
	if credential := runtime.NewCredential(); credential != nil {
		fmt.Printf("node credential generated: %s\n", credential.String())
		fmt.Println("copy it into the CLI now; it is not printed again")
	}

	runtime.Report()

	ctx, stop := contextFromSignals(signals)
	defer stop()

	return serveNode(ctx, runtime, logger)
}

// serveNode builds the dispatcher and the dialer and serves until the context ends.
//
// The context is a parameter so a test can drive the whole tail of the process without
// signalling the test binary.
//
// The identity comes from the runtime's holder rather than from a second read of the
// file, so the value the dialer validates is the value the deny list was built from. The
// holder is shared with the dispatcher, so an identifier regenerated while the Node runs
// is adopted by both components at once: the dialer announces the new identity and the
// dispatcher checks requests against it.
func serveNode(ctx context.Context, runtime *node.Runtime, logger *slog.Logger) error {
	holder := runtime.IdentityHolder()
	config := runtime.Config()

	dispatcher, err := node.NewDispatcher(runtime.Authority(), holder, config.ReplayWindow, config.ReplayCapacity, logger)
	if err != nil {
		return err
	}

	dialer, err := node.NewDialerWithHolder(config, holder, dispatcher, logger)
	if err != nil {
		return err
	}

	return dialer.Run(ctx)
}

// contextFromSignals returns a context cancelled when a signal arrives on the channel,
// plus the cancel function that releases the watcher.
//
// The channel is a parameter so a test can deliver a signal without signalling the test
// process: a real signal would make the test depend on the order in which two handlers
// register, and a mistake there would kill the test binary instead of failing the test.
func contextFromSignals(signals <-chan os.Signal) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(context.Background())

	go func() {
		select {
		case <-signals:
			cancel()
		case <-ctx.Done():
		}
	}()

	return ctx, cancel
}

// runID prints the node id and nothing else, so it can be copied into a script.
//
// Only the config directory is resolved, not the whole configuration. `id` never dials,
// so requiring a dial target or a tunnel token would make the documented first-run order
// impossible: the operator is told to run `id` before the tunnel token is configured,
// and a full configuration load refuses that order. The dial path keeps its own strict
// load, because a Node that started without a secret would be a Node whose operator
// believes it is serving something it is not.
func runID(arguments []string) error {
	flags := flag.NewFlagSet("id", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	nodeID, _, err := node.EnsureIdentity(node.IdentityPath(configDir))
	if err != nil {
		return err
	}

	fmt.Println(nodeID)
	return nil
}

// runRegenerate replaces the identity file with a fresh node id and prints it.
//
// Regeneration changes the address, not the credential. The credentials the Node accepts
// live in a separate file, so regenerating the identifier does not revoke a caller, and
// revoking a caller does not change the address. Regeneration is local and
// operator-initiated: the Server cannot trigger it, because a Server that could force
// regeneration could also force a denial of service.
func runRegenerate(arguments []string) error {
	flags := flag.NewFlagSet("regenerate", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	// Only the config directory is resolved, for the same reason as `id`: regeneration
	// rewrites the identity file and never dials, so requiring a dial target or a tunnel
	// token would make a local address change depend on a Server the operator may not
	// have configured yet.
	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	nodeID, err := node.RegenerateIdentity(node.IdentityPath(configDir))
	if err != nil {
		return err
	}

	fmt.Println(nodeID)
	return nil
}

// runCredential manages the credentials this Node accepts.
//
// The subcommand exists because the credential file is the only place a caller is
// authorized to talk to this Node, and an operator who must hand-edit a YAML file to add
// a caller will eventually hand-edit it wrong. The commands are deliberately small: add
// one credential, list the public key identifiers, and remove one. Rotation is
// add-then-remove, which is the only order that does not lock a caller out between two
// commands.
func runCredential(arguments []string) error {
	if len(arguments) == 0 {
		return fmt.Errorf("credential needs a subcommand: add, list or remove")
	}
	subcommand := arguments[0]
	rest := arguments[1:]

	switch subcommand {
	case "add":
		return runCredentialAdd(rest)
	case "list":
		return runCredentialList(rest)
	case "remove":
		return runCredentialRemove(rest)
	default:
		return fmt.Errorf("unknown credential subcommand %q; want add, list or remove", subcommand)
	}
}

// runCredentialAdd generates a credential and appends it to the file.
//
// The generated credential is printed once. It is the only moment the secret exists
// outside the file, so the operator must copy it into the CLI before the command's output
// is lost.
func runCredentialAdd(arguments []string) error {
	flags := flag.NewFlagSet("credential add", flag.ContinueOnError)
	keyID := flags.String("key-id", "", "public key id to name the credential; empty generates one")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}
	path := node.CredentialsPath(configDir)

	credentials, err := node.LoadCredentialList(path)
	if err != nil && !errors.Is(err, node.ErrCredentialsMissing) {
		return err
	}

	var created security.Credential
	if *keyID == "" {
		created, err = security.NewCredential()
	} else {
		created, err = security.NewCredentialWithKeyID(*keyID)
	}
	if err != nil {
		return err
	}
	credentials = append(credentials, created)

	if err := node.SaveCredentials(path, credentials); err != nil {
		return err
	}

	fmt.Println(created.String())
	return nil
}

// runCredentialList prints the public key identifiers.
//
// It never prints a secret. An operator who needs the secret has lost it, and the answer
// is to add a new credential rather than to recover the old one: a file that could print
// a secret is a file that can leak one.
func runCredentialList(arguments []string) error {
	flags := flag.NewFlagSet("credential list", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	credentials, err := node.LoadCredentials(node.CredentialsPath(configDir))
	if err != nil {
		return err
	}
	for _, keyID := range credentials.KeyIDs() {
		fmt.Println(keyID)
	}
	return nil
}

// runCredentialRemove removes one credential by key identifier.
//
// The removal is a rewrite of the file rather than an in-place edit, so a failure leaves
// the previous set in force instead of a half-written file. Removing the last credential
// is refused: a Node with no credential accepts nothing, which looks exactly like a Node
// whose policy denies everything, and an operator who did that by accident would debug
// the policy instead of the credential file.
func runCredentialRemove(arguments []string) error {
	flags := flag.NewFlagSet("credential remove", flag.ContinueOnError)
	keyID := flags.String("key-id", "", "public key id to remove")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}
	if *keyID == "" {
		return fmt.Errorf("--key-id is required")
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}
	path := node.CredentialsPath(configDir)

	existing, err := node.LoadCredentialList(path)
	if err != nil {
		return err
	}

	remaining := make([]security.Credential, 0, len(existing))
	found := false
	for _, candidate := range existing {
		if candidate.KeyID == *keyID {
			found = true
			continue
		}
		remaining = append(remaining, candidate)
	}
	if !found {
		return fmt.Errorf("no credential with key id %q", *keyID)
	}
	if len(remaining) == 0 {
		return fmt.Errorf("refusing to remove the last credential; a node with no credential accepts nothing")
	}

	return node.SaveCredentials(path, remaining)
}
