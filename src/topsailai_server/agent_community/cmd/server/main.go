// Package main is the entry point for the ACS HTTP server.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/topsailai/agent-community/internal/agent"
	"github.com/topsailai/agent-community/internal/api"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/daemon"
	"github.com/topsailai/agent-community/internal/db"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/internal/lock"
	"github.com/topsailai/agent-community/internal/nats"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/internal/workpool"
	"github.com/topsailai/agent-community/pkg/logger"
)

// autoTriggerLockManagerAdapter adapts *lock.DistributedLock to the
// nats.AutoTriggerLockManager interface. The concrete *lock.Lock already
// implements nats.AutoTriggerLock, but the method return type must match
// exactly, so this thin wrapper is required.
type autoTriggerLockManagerAdapter struct {
	lm *lock.DistributedLock
}

func (a *autoTriggerLockManagerAdapter) Acquire(ctx context.Context, lockType, resourceID string) (nats.AutoTriggerLock, error) {
	l, err := a.lm.Acquire(ctx, lockType, resourceID)
	if err != nil {
		return nil, err
	}
	return l, nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "server failed: %v\n", err)
		os.Exit(1)
	}
}
func run() error {
	cmd, _, err := parseArgs(os.Args[1:])
	if err != nil {
		return err
	}

	switch cmd {
	case "":
		return runServer(false)
	case "start":
		return handleStart()
	case "daemon-internal":
		return runServer(true)
	case "stop":
		return handleStop()
	case "restart":
		return handleRestart()
	case "status":
		return handleStatus()
	case "help":
		printUsage()
		return nil
	default:
		return fmt.Errorf("unknown command: %s", cmd)
	}
}

// parseArgs parses the command-line arguments for the server binary.
// It returns the resolved subcommand, whether the server should run in daemon
// mode, and any parsing error. An empty command means run in foreground.
func parseArgs(args []string) (string, bool, error) {
	if len(args) == 0 {
		return "", false, nil
	}

	subcommand := args[0]
	switch subcommand {
	case "start":
		return "start", true, nil
	case "-d", "--daemon-internal":
		return "daemon-internal", true, nil
	case "stop", "restart", "status":
		return subcommand, false, nil
	case "-h", "--help", "help":
		return "help", false, nil
	default:
		return "", false, fmt.Errorf("unknown command: %s", subcommand)
	}
}

func printUsage() {
	fmt.Println("Usage: server [command]")
	fmt.Println("")
	fmt.Println("Commands:")
	fmt.Println("  start   Start the server in daemon mode (background)")
	fmt.Println("  stop    Stop the running server")
	fmt.Println("  restart Restart the server")
	fmt.Println("  status  Show the server status")
	fmt.Println("  help    Show this help message")
	fmt.Println("")
	fmt.Println("Environment variables:")
	fmt.Println("  TOPSAILAI_HOME    Base directory for logs and PID files (default: /topsailai)")
	fmt.Println("")
	fmt.Println("Files:")
	fmt.Printf("  Log: %s\n", daemon.GetLogPath())
	fmt.Printf("  PID: %s\n", daemon.GetPIDPath())
}

func handleStart() error {
	return daemon.Start()
}

func handleStop() error {
	return daemon.Stop()
}

func handleRestart() error {
	return daemon.Restart()
}

func handleStatus() error {
	result, err := daemon.Status()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error checking status: %v\n", err)
		os.Exit(1)
	}

	if result.Running {
		fmt.Printf("Server is running (PID: %d)\n", result.PID)
		fmt.Printf("PID file: %s\n", result.PIDPath)
		fmt.Printf("Log file: %s\n", result.LogPath)
	} else {
		fmt.Println("Server is not running")
		if result.PID > 0 {
			fmt.Printf("(stale PID file found: %s)\n", result.PIDPath)
		}
	}
	return nil
}

func runServer(isDaemon bool) error {
	// If running in daemon mode, setup daemon environment
	if isDaemon {
		if err := daemon.SetupDaemon(); err != nil {
			return fmt.Errorf("failed to setup daemon: %w", err)
		}
		// Cleanup PID file on shutdown
		defer daemon.CleanupDaemon()
	}

	// 1. Load configuration from environment variables.
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("failed to load config: %w", err)
	}

	// 2. Initialize logger.
	log := logger.New(logger.Config{
		Output:     cfg.Log.Output,
		Level:      cfg.Log.Level,
		FilePath:   cfg.Log.FilePath,
		MaxSize:    cfg.Log.MaxSize,
		MaxAge:     cfg.Log.MaxAge,
		MaxBackups: cfg.Log.MaxBackups,
	})
	logger.InitDefault(logger.Config{
		Output:     cfg.Log.Output,
		Level:      cfg.Log.Level,
		FilePath:   cfg.Log.FilePath,
		MaxSize:    cfg.Log.MaxSize,
		MaxAge:     cfg.Log.MaxAge,
		MaxBackups: cfg.Log.MaxBackups,
	})

	log.Info("server", "", "starting ACS server", "port", cfg.Server.Port)

	// 3. Connect to database (auto-create, auto-migrate).
	database, err := db.New(cfg)
	if err != nil {
		return fmt.Errorf("failed to initialize database: %w", err)
	}
	defer func() {
		if err := database.Close(); err != nil {
			log.Error("server", "", "failed to close database", "error", err.Error())
		}
	}()

	// 4. Connect to NATS (create streams, consumers, KV bucket).
	natsClient := nats.NewClient(&cfg.NATS)
	if err := natsClient.Connect(); err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer natsClient.Close()

	js := natsClient.JetStream()
	kv := natsClient.KV()

	// 5. Create distributed lock manager.
	lockManager, err := lock.NewDistributedLock(js, "acs_locks")
	if err != nil {
		return fmt.Errorf("failed to create distributed lock manager: %w", err)
	}
	_ = lockManager
	// 5.5. Initialize account services and run bootstrap for default accounts.
	auditSvc := services.NewAuditLogService(database.Conn)
	accountSvc := services.NewAccountService(database.Conn, cfg, auditSvc)
	apiKeySvc := services.NewAPIKeyService(database.Conn, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)

	bootstrapSvc := services.NewBootstrapService(database.Conn, cfg, accountSvc, apiKeySvc, auditSvc, kv, log)
	if err := bootstrapSvc.Run(context.Background()); err != nil {
		return fmt.Errorf("failed to bootstrap default accounts: %w", err)
	}

	// 6. Create NATS publisher.
	publisher := nats.NewPublisher(js)

	// 7. Create trigger evaluator.
	evaluator := trigger.NewEvaluator(cfg.Agent.AutoTriggerTimeout)

	// 8. Create work pool for concurrency control.
	pool := workpool.NewPool(cfg.AgentWorkPool.PerNode, cfg.AgentWorkPool.PerUser, cfg.AgentWorkPool.PerGroup)

	// 9. Create agent executor.
	executor := agent.NewExecutor()

	// 10. Create NATS consumer (AgentWorkPool processor).
	consumer := nats.NewConsumer(database.Conn, publisher, executor, accountSvc, pool, cfg)
	// 11. Create and start NATS consumer subscription.
	sub, err := natsClient.CreatePendingMessageConsumer(consumer.Handler())
	if err != nil {
		return fmt.Errorf("failed to create pending message consumer: %w", err)
	}
	defer func() {
		if err := sub.Unsubscribe(); err != nil {
			log.Error("server", "", "failed to unsubscribe from NATS consumer", "error", err.Error())
		}
	}()

	// 12. Create and start auto-trigger periodic task.
	autoTrigger := nats.NewAutoTrigger(
		database.Conn,
		js,
		publisher,
		evaluator,
		&autoTriggerLockManagerAdapter{lm: lockManager},
		cfg.Agent.AutoTriggerTimeout/10, // check interval = timeout/10, min 1m
		cfg.Agent.AutoTriggerTimeout,
	)
	autoTrigger.Start()
	defer autoTrigger.Stop()

	// 12.5. Create and start cleanup periodic task for agent_message_processing.
	cleanupTask := db.NewCleanupTask(database.Conn, cfg.Cleanup)
	cleanupTask.Start()
	defer cleanupTask.Stop()

	// 12.6. Create and register service discovery (if enabled).
	var disc *discovery.Discovery
	if cfg.Discovery.Enabled {
		disc, err = discovery.New(js, discovery.Config{
			ServiceName: cfg.Discovery.ServiceName,
			Address:     cfg.Server.GetListenAddress(),
			Port:        cfg.Server.Port,
			Version:     "1.0.0",
			BucketName:  cfg.Discovery.BucketName,
			Heartbeat:   cfg.Discovery.Heartbeat,
			TTL:         cfg.Discovery.TTL,
		})
		if err != nil {
			return fmt.Errorf("failed to create service discovery: %w", err)
		}
		if err := disc.Register(); err != nil {
			return fmt.Errorf("failed to register service: %w", err)
		}
		defer func() {
			log.Info("server", "", "deregistering service from discovery")
			if err := disc.Deregister(); err != nil {
				log.Error("server", "", "failed to deregister service", "error", err.Error())
			}
		}()
	}

	// 13. Create HTTP API router and server.
	router := api.NewRouter(cfg, database.Conn, publisher, evaluator, disc, log)
	server := api.NewServer(cfg, router, log)

	// 14. Handle OS signals for graceful shutdown.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// Start server in a goroutine.
	errCh := make(chan error, 1)
	go func() {
		if err := server.Start(); err != nil {
			errCh <- err
		}
	}()

	log.Info("server", "", "ACS server started successfully",
		"port", cfg.Server.Port,
		"nats_servers", cfg.NATS.Servers,
	)

	select {
	case err := <-errCh:
		log.Error("server", "", "server error", "error", err.Error())
		return err
	case sig := <-sigCh:
		log.Info("server", "", "received shutdown signal", "signal", sig.String())
	}

	// Graceful shutdown order:
	// 1. HTTP server
	// 2. NATS consumer subscription
	// 3. Auto-trigger task
	// 4. Service discovery deregistration (handled by defer)
	// 5. NATS connection
	// 6. Database (handled by defer)

	log.Info("server", "", "shutting down HTTP server")
	if err := server.Shutdown(); err != nil {
		log.Error("server", "", "HTTP server shutdown error", "error", err.Error())
	}

	log.Info("server", "", "unsubscribing from NATS consumer")
	if err := sub.Unsubscribe(); err != nil {
		log.Error("server", "", "NATS consumer unsubscribe error", "error", err.Error())
	}

	log.Info("server", "", "stopping auto-trigger task")
	autoTrigger.Stop()

	log.Info("server", "", "closing NATS connection")
	natsClient.Close()

	log.Info("server", "", "closing database connection")
	if err := database.Close(); err != nil {
		log.Error("server", "", "database close error", "error", err.Error())
	}

	log.Info("server", "", "ACS server stopped gracefully")
	return nil
}
