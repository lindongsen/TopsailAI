// Command connector-server is the cloud-side entry point. It accepts Node
// connections and calls the operations a Node advertises.
//
// The process serves two surfaces from one listener: the channel at /channel,
// where a Node dials in, and the CLI API at /v1/nodes/{node_id}/operations, where
// an operator calls an operation. Both are served from one port behind one TLS
// certificate, because the two surfaces share the routing registry and a second
// port would not isolate state.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"topsailai_connector/internal/helpdispatch"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
	"topsailai_connector/internal/serverhelp"
)

func main() {
	os.Exit(exitStatus(run(os.Args[1:])))
}

// exitStatus maps the result of run to a process exit status.
//
// The mapping lives here rather than inside run so run can stay a function that returns
// an error, which is what makes it testable. The three statuses are the ones the help
// text promises: 0 for success, 1 for a failure, 2 for a command line that was rejected
// before anything was done. A usage error must be 2 and not 1, because the message
// begins with "usage:" and a script branches on the status rather than on the text.
func exitStatus(err error) int {
	if err == nil {
		return 0
	}

	// A refusal that already wrote its own message carries only a status, so it must not
	// be printed again. Printing it twice would show the operator the same sentence in
	// two places and make the second copy look like a second failure.
	var printed *helpdispatch.PrintedError
	if errors.As(err, &printed) {
		return printed.Status
	}

	// A subcommand that reports its own status carries it here. The `cli` subcommand is
	// the one such case: it must exit non-zero on an error code so a shell script can
	// branch on it, and it has already written its own message.
	var status *statusError
	if errors.As(err, &status) {
		return status.Status
	}

	fmt.Fprintf(os.Stderr, "connector-server: %v\n", err)
	if helpdispatch.IsUsage(err) {
		return 2
	}
	return 1
}

// statusError carries an exit status from a subcommand that decides its own.
//
// It exists so `cli` can return a status through the error-returning shape of run
// instead of calling os.Exit in the middle. A subcommand that exits the process cannot
// be tested, and it also skips every deferred cleanup between it and main.
type statusError struct {
	// Status is the exit status the subcommand decided.
	Status int
}

// Error returns an empty message, because the subcommand already wrote its own.
func (e *statusError) Error() string {
	return ""
}

// run is the whole process, separated from main so a test can call it and so
// every failure returns an error instead of calling os.Exit in the middle.
//
// The `cli` subcommand is the one exception to the error-returning shape: it
// returns an exit status instead, because a CLI must exit non-zero on an error
// code so a shell script can branch on it.
func run(arguments []string) error {
	// The informational forms are answered before the subcommand is split, because
	// `--help` is not a flag of any subcommand: it is a request about the program. Doing
	// it first also means `connector-server --help` works without naming `run`, which is
	// what an operator types when they do not yet know that `run` exists.
	if result := helpdispatch.Resolve(programName, arguments, catalog()); result.Handled {
		if result.Stdout != "" {
			fmt.Fprint(os.Stdout, result.Stdout)
		}
		if result.Stderr != "" {
			fmt.Fprint(os.Stderr, result.Stderr)
		}
		if result.Status != 0 {
			return &helpdispatch.PrintedError{Status: result.Status}
		}
		return nil
	}

	command, rest := splitCommand(arguments)

	switch command {
	case "", "run":
		return runServer(rest)
	case "cli":
		return &statusError{Status: cli.Run(rest, os.Getenv, os.Stdout, os.Stderr)}
	default:
		return helpdispatch.Usagef("unknown command %q; want run or cli", command)
	}
}

// programName is the name used as the prefix of every message and in the help text.
//
// It is a constant rather than the executable's base name, because the help text names
// the program in every synopsis line and a renamed copy would then print a synopsis the
// operator cannot type.
const programName = "connector-server"

// catalog is the set of pages this binary can print.
//
// The `cli` page points at the CLI's own help rather than repeating it. That subcommand
// has a complete help covering every flag, every environment variable, every error code
// and every exit status, and two copies of one interface drift apart.
func catalog() helpdispatch.Catalog {
	return helpdispatch.Catalog{
		Main:    serverhelp.Main(programName),
		Version: helpdispatch.Version(programName),
		Pages: map[string]string{
			"run": serverhelp.Run(programName),
			"cli": serverhelp.CLI(programName),
		},
		Commands: []string{"run", "cli"},
	}
}

// splitCommand separates the subcommand from its flags. A leading flag means the
// default subcommand, so `connector-server --help` works without naming `run`.
//
// A leading word that is not a known command is returned as the command, so `run`
// reports it as unknown instead of starting the Server: a typo that silently
// started the default subcommand is a typo an operator never learns about.
func splitCommand(arguments []string) (string, []string) {
	if len(arguments) == 0 {
		return "", nil
	}
	switch arguments[0] {
	case "run", "cli":
		return arguments[0], arguments[1:]
	}
	first := arguments[0]
	if len(first) > 0 && first[0] == '-' {
		return "", arguments
	}
	return first, arguments[1:]
}

// runServer loads the configuration, validates both secrets and serves the two
// surfaces until the process is asked to stop.
//
// Every failure here is a startup failure. A Server that started with a missing
// or short secret would authenticate callers it should refuse, and the mistake
// would surface as a successful request rather than as a refusal.
func runServer(arguments []string) error {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))

	config, err := server.LoadConfig(os.Getenv)
	if err != nil {
		return err
	}

	// The registry is created here and handed to the listener, so the channel
	// surface and the CLI surface share one routing table. Two registries would
	// let a Node register into one while the CLI looked in the other, and the
	// symptom would be a Node that looks connected and answers node_offline.
	registry := server.NewRegistry()

	listener, err := server.NewListener(config, registry, logger)
	if err != nil {
		return err
	}

	logger.Info("connector-server starting",
		"protocol", protocol.Version,
		"config", config.Redacted(),
		"listen", listener.Addr(),
	)

	ctx, stop := signalContext()
	defer stop()

	return listener.Serve(ctx)
}

// signalContext returns a context cancelled when the process is asked to stop.
//
// The cancellation is what makes a shutdown orderly: Serve closes the HTTP server
// and every live channel when the context ends, so a Node that is mid-request is
// answered instead of being cut off by a process that vanished. A Server that
// exited without closing its listener would leave the port bound until the
// operating system reclaimed it, which on Windows is long enough to make an
// immediate restart fail.
func signalContext() (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(context.Background())

	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)

	go func() {
		defer signal.Stop(signals)
		select {
		case <-signals:
			cancel()
		case <-ctx.Done():
		}
	}()

	return ctx, cancel
}
