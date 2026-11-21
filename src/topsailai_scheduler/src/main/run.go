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
	"strings"
	"syscall"

	"topsailai_scheduler/config"
	"topsailai_scheduler/control"
	"topsailai_scheduler/daemon"
	"topsailai_scheduler/launcher"
	"topsailai_scheduler/logging"
	"topsailai_scheduler/provider"
	"topsailai_scheduler/task"
)

// runDaemon starts the scheduler and its control socket, then blocks until a
// termination signal arrives.
//
// The daemon and the control server share one context, so a signal stops both:
// the socket stops accepting requests and the scheduler drains its runs.
func runDaemon(args []string) int {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	tasksRoot := flags.String("tasks-root", "", "tasks folder, overrides "+config.EnvTasksRoot)
	if _, err := parseFlags(flags, args); err != nil {
		return exitUsage
	}
	if flags.NArg() > 0 {
		return usageError("run takes no arguments, got %q", flags.Args())
	}

	cfg, err := config.Load()
	if err != nil {
		return fail("invalid configuration: %v", err)
	}

	cfg, err = applyTasksRootOverride(cfg, *tasksRoot)
	if err != nil {
		return fail("invalid configuration: %v", err)
	}

	logger, closer, err := logging.New(logging.Options{
		Level:      cfg.LogLevel,
		Output:     cfg.LogOutput,
		MaxSizeMB:  cfg.LogMaxSizeMB,
		MaxBackups: cfg.LogMaxBackups,
		MaxAgeDays: cfg.LogMaxAgeDays,
		Compress:   cfg.LogCompress,
	})
	if err != nil {
		return fail("build logger: %v", err)
	}
	defer func() {
		if closeErr := closer.Close(); closeErr != nil {
			fmt.Fprintf(os.Stderr, "close log: %v\n", closeErr)
		}
	}()

	socketPath, err := cfg.AbsoluteControlSocket()
	if err != nil {
		return fail("resolve control socket: %v", err)
	}

	providerPath, err := resolveDefaultProviderPath(cfg)
	if err != nil {
		return fail("%v", err)
	}
	providers := provider.NewResolver(provider.ResolverOptions{
		CallTimeout:    cfg.ProviderCallTimeout,
		MaxOutputBytes: cfg.MaxOutputBytes,
	})

	scheduler := daemon.New(cfg, logger, task.NewFilesystemSource(cfg.TasksRoot, cfg.MinContentRunes), launcher.DefaultRegistry(), providers, providerPath)
	server := control.NewServer(scheduler, socketPath, logging.Module(logger, "control"))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	serverErrors := make(chan error, 1)
	go func() { serverErrors <- server.Serve(ctx) }()

	daemonErrors := make(chan error, 1)
	go func() { daemonErrors <- scheduler.Run(ctx) }()

	select {
	case err := <-daemonErrors:
		// The scheduler ended on its own, so the socket must not outlive it.
		closeServer(server, logger)
		if err != nil {
			return fail("scheduler stopped: %v", err)
		}
		return exitOK
	case err := <-serverErrors:
		// A control channel that cannot serve makes the daemon unreachable, so
		// the process stops instead of running without a way to be controlled.
		stop()
		if err != nil {
			<-daemonErrors
			return fail("control socket stopped: %v", err)
		}
		<-daemonErrors
		return exitOK
	}
}

// closeServer closes the control server and logs a failure instead of ignoring
// it, because a socket left behind blocks the next start.
func closeServer(server *control.Server, logger *slog.Logger) {
	if err := server.Close(); err != nil && !errors.Is(err, io.EOF) {
		logger.Warn("close control server failed", slog.String("error", err.Error()))
	}
}

// applyTasksRootOverride lets the command line win over the environment.
//
// The flag is the more specific intent, while the environment stays the
// fallback for a bare "scheduler run". Validation is repeated because the
// override happens after Load already validated the environment-derived value.
func applyTasksRootOverride(cfg config.Config, tasksRoot string) (config.Config, error) {
	value := strings.TrimSpace(tasksRoot)
	if value == "" {
		return cfg, nil
	}
	cfg.TasksRoot = value
	if err := cfg.Validate(); err != nil {
		return config.Config{}, err
	}
	return cfg, nil
}

// resolveDefaultProviderPath returns the absolute provider executable the
// scheduler uses for a task that names none.
//
// The path is required, not defaulted: a scheduler with no provider cannot run
// anything, and guessing a location would turn a missing configuration into a
// confusing failure at the first due task instead of a clear refusal to start.
// The check lives here rather than in config.Validate because the CLI commands
// share Load and never resolve a provider: only the daemon needs one.
func resolveDefaultProviderPath(cfg config.Config) (string, error) {
	if strings.TrimSpace(cfg.DefaultProviderPath) == "" {
		return "", fmt.Errorf("%s must be set: the scheduler needs a provider executable to run tasks", config.EnvDefaultProviderPath)
	}
	absolute, err := cfg.AbsoluteDefaultProviderPath()
	if err != nil {
		return "", fmt.Errorf("resolve default provider path: %w", err)
	}
	return absolute, nil
}
