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

// runServer loads the configuration, validates both secrets and serves the two
// surfaces until the process is asked to stop.
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
