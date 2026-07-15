// topsailai_data is the command-line interface for the topsailai_data object
// storage system. It loads configuration from environment variables, initializes
// the configured metadata and actual-data adapters, and dispatches user
// commands through the cli package.
package main

import (
	"context"
	"fmt"
	"os"

	"github.com/topsailai/topsailai_data/pkg/cli"
	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/manager"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("load configuration: %w", err)
	}

	mgr, err := manager.New(cfg)
	if err != nil {
		return fmt.Errorf("initialize manager: %w", err)
	}
	defer func() {
		_ = mgr.Close()
	}()

	return cli.Run(context.Background(), mgr, os.Args[1:])
}
