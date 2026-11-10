// Command connector-node is the personal-computer entry point. It dials the
// Server, keeps the link open and serves the operations its policy allows.
//
// This build starts the process, loads the configuration, loads the policy,
// opens every scope the policy defines and prepares the node identity. The
// dialer, the handshake and the operation dispatch are added by later logical
// units, so the process reports readiness and then waits for a signal.
package main

import (
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

// runNode starts the Node: configuration, identity, policy, scopes, then wait.
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
	if identity, generated := runtime.NewIdentity(); generated {
		fmt.Printf("node identity generated: %s\n", identity.String())
	}

	runtime.Report()

	// The signal channel is created here rather than inside waitForShutdown, so
	// the wait can be tested without sending a signal to the test process.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	return waitForShutdown(logger, signals)
}

// waitForShutdown blocks until a signal arrives, then returns so the deferred
// cleanup runs. A Node that exited without releasing its scope handles would
// leave a directory that cannot be removed on Windows.
//
// The channel is a parameter so a test can deliver a signal without signalling
// the test process: a real signal would make the test depend on the order in
// which two handlers register, and a mistake there would kill the test binary
// instead of failing the test.
func waitForShutdown(logger *slog.Logger, signals <-chan os.Signal) error {
	received := <-signals
	logger.Info("connector-node stopping", "signal", received.String())
	return nil
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
