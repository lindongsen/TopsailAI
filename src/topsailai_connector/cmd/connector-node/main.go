// Command connector-node is the personal-computer entry point. It dials the
// Server, keeps the link open and serves the operations its policy allows.
//
// The process loads the configuration, loads the policy, opens every scope the
// policy defines, prepares the node identity and then dials the Server. It never
// listens: the Node is the side that initiates, so a personal computer needs no
// inbound port, no public address and no firewall change.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "connector-node: %v\n", err)
		os.Exit(1)
	}
}

// run is the whole process, separated from main so a test can call it and so
// every failure returns an error instead of calling os.Exit in the middle.
func run(arguments []string) error {
	command, rest := splitCommand(arguments)

	switch command {
	case "", "run":
		return runNode(rest)
	case "id":
		return runID(rest)
	case "regenerate":
		return runRegenerate(rest)
	default:
		return fmt.Errorf("unknown command %q; want run, id or regenerate", command)
	}
}

// splitCommand separates the subcommand from its flags.
//
// A leading flag means the default subcommand, so `connector-node --help` works
// without naming `run`. A leading word that is not a known command is returned as
// the command, so `run` reports it as unknown instead of starting the Node: a
// typo that silently starts the default subcommand is a typo an operator never
// learns about.
func splitCommand(arguments []string) (string, []string) {
	if len(arguments) == 0 {
		return "", nil
	}
	switch arguments[0] {
	case "run", "id", "regenerate":
		return arguments[0], arguments[1:]
	}
	if strings.HasPrefix(arguments[0], "-") {
		return "", arguments
	}
	return arguments[0], arguments[1:]
}

// runNode starts the Node: configuration, identity, policy, scopes, then dial.
//
// The order is deliberate. The runtime is opened first, because it loads the
// identity and the policy and refuses to start when either is unusable; a dialer
// built before that would connect to the Server and then discover it has nothing
// to serve. The dialer is built last, so a Node that cannot serve never appears
// connected.
func runNode(arguments []string) error {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
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

	// A generated pair is printed once, at the moment it is created, because the
	// operator has to copy it into a CLI and there is no lookup endpoint. It goes
	// to stdout rather than to the log, so a log file does not accumulate
	// credentials.
	identity, generated := runtime.NewIdentity()
	if generated {
		fmt.Printf("node identity generated: %s\n", identity.String())
	}

	runtime.Report()

	// The identity comes from the runtime rather than from a second read of the
	// file, so the value the dialer validates is the value the deny list was built
	// from. Reading it twice would let a regeneration between the two reads leave
	// the process serving under an identity it no longer owns.
	dispatcher := node.NewDispatcher(runtime.Authority(), identity, logger)

	dialer, err := node.NewDialer(runtime.Config(), identity, dispatcher, logger)
	if err != nil {
		return err
	}

	// The signal channel is created here rather than inside contextFromSignals, so
	// the wait can be tested without sending a signal to the test process.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	ctx, stop := contextFromSignals(signals)
	defer stop()

	return dialer.Run(ctx)
}

// contextFromSignals returns a context cancelled when a signal arrives on the
// channel, plus the cancel function that releases the watcher.
//
// The channel is a parameter so a test can deliver a signal without signalling
// the test process: a real signal would make the test depend on the order in
// which two handlers register, and a mistake there would kill the test binary
// instead of failing the test.
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

// runID prints the node-id.node-token pair and nothing else, so it can be copied
// into a script. It prints a secret, so the operator must treat the output as
// one: it must not be pasted into a ticket, a chat message or a retained shell
// history.
func runID(arguments []string) error {
	flags := flag.NewFlagSet("id", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}

	config, err := node.LoadConfig(os.Getenv)
	if err != nil {
		return err
	}

	identity, _, err := node.EnsureIdentity(node.IdentityPath(config.ConfigDir))
	if err != nil {
		return err
	}

	fmt.Println(identity.String())
	return nil
}

// runRegenerate replaces the identity file with a fresh pair and prints it.
//
// Regeneration is local and operator-initiated. The Server cannot trigger it,
// because a Server that could force regeneration could also force a denial of
// service.
func runRegenerate(arguments []string) error {
	flags := flag.NewFlagSet("regenerate", flag.ContinueOnError)
	keepID := flags.Bool("keep-id", false, "keep the node id and replace only the token")
	if err := flags.Parse(arguments); err != nil {
		return err
	}

	config, err := node.LoadConfig(os.Getenv)
	if err != nil {
		return err
	}

	identity, err := node.RegenerateIdentity(node.IdentityPath(config.ConfigDir), *keepID)
	if err != nil {
		return err
	}

	fmt.Println(identity.String())
	return nil
}
