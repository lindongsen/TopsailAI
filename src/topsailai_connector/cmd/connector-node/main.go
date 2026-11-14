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

// rejectStrayArguments refuses a positional argument that no flag consumed.
//
// flag.Parse accepts a positional argument and leaves it in Args(), so a word
// that is not a flag is silently dropped by a caller that never checks. That is
// how `connector-node run serve` used to start the Node: `serve` was parsed as a
// positional argument, ignored, and the default subcommand ran. A word the
// operator typed must either be a flag or be refused, because a silently ignored
// word is a typo the operator never learns about.
func rejectStrayArguments(flags *flag.FlagSet) error {
	if flags.NArg() == 0 {
		return nil
	}
	return fmt.Errorf("unexpected argument %q; want flags only", flags.Arg(0))
}

// runNode starts the Node: configuration, identity, policy, scopes, then dial.
//
// The order is deliberate. The runtime is opened first, because it loads the
// identity and the policy and refuses to start when either is unusable; a dialer
// built before that would connect to the Server and then discover it has nothing
// to serve. The dialer is built last, so a Node that cannot serve never appears
// connected.
func runNode(arguments []string) error {
	// The signal channel is created here rather than inside runNodeWithSignals, so
	// the whole process can be tested without sending a signal to the test binary.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	return runNodeWithSignals(arguments, signals)
}

// runNodeWithSignals is runNode with the signal channel supplied by the caller.
//
// The channel is a parameter so a test can drive the complete process, including
// the dial, without signalling the test binary: a real signal would make the test
// depend on the order in which two handlers register, and a mistake there would
// kill the test binary instead of failing the test.
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

	// A generated pair is printed once, at the moment it is created, because the
	// operator has to copy it into a CLI and there is no lookup endpoint. It goes
	// to stdout rather than to the log, so a log file does not accumulate
	// credentials.
	identity, generated := runtime.NewIdentity()
	if generated {
		fmt.Printf("node identity generated: %s\n", identity.String())
	}

	runtime.Report()

	ctx, stop := contextFromSignals(signals)
	defer stop()

	return serveNode(ctx, runtime, logger)
}

// serveNode builds the dispatcher and the dialer and serves until the context
// ends.
//
// The context is a parameter so a test can drive the whole tail of the process
// without signalling the test binary.
//
// The identity comes from the runtime's holder rather than from a second read of
// the file, so the value the dialer validates is the value the deny list was built
// from. The holder is shared with the dispatcher, so a pair regenerated while the
// Node runs is adopted by both components at once: the dialer announces the new
// identity and the dispatcher checks requests against it, which is what makes
// `connector-node regenerate` invalidate the previous token immediately.
func serveNode(ctx context.Context, runtime *node.Runtime, logger *slog.Logger) error {
	holder := runtime.IdentityHolder()

	dispatcher := node.NewDispatcherWithHolder(runtime.Authority(), holder, logger)

	dialer, err := node.NewDialerWithHolder(runtime.Config(), holder, dispatcher, logger)
	if err != nil {
		return err
	}

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
//
// Only the config directory is resolved, not the whole configuration. `id` never
// dials, so requiring a dial target or a tunnel token would make the documented
// first-run order impossible: the operator is told to run `id` before the tunnel
// token is configured, and a full configuration load refuses that order. The
// dial path keeps its own strict load, because a Node that started without a
// secret would be a Node whose operator believes it is serving something it is
// not.
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

	identity, _, err := node.EnsureIdentity(node.IdentityPath(configDir))
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
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	// Only the config directory is resolved, for the same reason as `id`:
	// regeneration rewrites the identity file and never dials, so requiring a
	// dial target or a tunnel token would make a local credential change depend
	// on a Server the operator may not have configured yet.
	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	identity, err := node.RegenerateIdentity(node.IdentityPath(configDir), *keepID)
	if err != nil {
		return err
	}

	fmt.Println(identity.String())
	return nil
}
