// Command connector-server is the cloud-side entry point. It accepts Node
// connections and calls the operations a Node advertises.
//
// This build loads and validates the configuration, reports readiness and waits
// for a signal. The listener, the channel registry and the CLI API are added by
// later logical units, so the process deliberately refuses to pretend it is
// serving: it validates everything it can validate and then says what it is not
// yet doing.
package main

import (
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "connector-server: %v\n", err)
		os.Exit(1)
	}
}

// run is the whole process, separated from main so a test can call it and so
// every failure returns an error instead of calling os.Exit in the middle.
//
// The `cli` subcommand is the one exception to the error-returning shape: it
// returns an exit status instead, because a CLI must exit non-zero on an error
// code so a shell script can branch on it.
func run(arguments []string) error {
	command, rest := splitCommand(arguments)

	switch command {
	case "", "run":
		return runServer(rest)
	case "cli":
		os.Exit(cli.Run(rest, os.Getenv, os.Stdout, os.Stderr))
		return nil
	default:
		return fmt.Errorf("unknown command %q; want run or cli", command)
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

// runServer loads the configuration, validates both secrets and waits for a
// shutdown signal.
//
// Every failure here is a startup failure. A Server that started with a missing
// or short secret would authenticate callers it should refuse, and the mistake
// would surface as a successful request rather than as a refusal.
func runServer(arguments []string) error {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	if err := flags.Parse(arguments); err != nil {
		return err
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))

	config, err := server.LoadConfig(os.Getenv)
	if err != nil {
		return err
	}

	logger.Info("connector-server starting",
		"protocol", protocol.Version,
		"config", config.Redacted(),
	)
	logger.Warn("connector-server is not listening yet; the channel listener and the CLI API are added by later logical units")

	return waitForShutdown(logger)
}

// waitForShutdown blocks until the process is asked to stop, then returns so the
// deferred cleanup runs. A Server that exited without closing its listener would
// leave the port bound until the operating system reclaimed it, which on Windows
// is long enough to make an immediate restart fail.
func waitForShutdown(logger *slog.Logger) error {
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	received := <-signals
	logger.Info("connector-server stopping", "signal", received.String())
	return nil
}
