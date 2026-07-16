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

// osExit is a variable so tests can replace os.Exit when calling main().
var osExit = os.Exit

func main() {
	osExit(run(os.Args[1:], realDependencies()))
}

// dependencies holds the injectable collaborators used by run().
// Tests replace these with stubs or fakes to exercise error paths without
// building a real manager.
type dependencies struct {
	loadConfig func() (*config.Config, error)
	newManager func(*config.Config) (*manager.Manager, error)
	runCLI     func(context.Context, *manager.Manager, []string) error
}

func realDependencies() dependencies {
	return dependencies{
		loadConfig: config.Load,
		newManager: manager.New,
		runCLI:     cli.Run,
	}
}

// run loads configuration, initializes the manager, and dispatches the CLI.
// It returns an exit code (0 for success, 1 for any error) so that both main()
// and unit tests can observe outcomes directly.
func run(args []string, deps dependencies) int {
	cfg, err := deps.loadConfig()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: load configuration: %v\n", err)
		return 1
	}

	mgr, err := deps.newManager(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: initialize manager: %v\n", err)
		return 1
	}
	defer func() {
		_ = mgr.Close()
	}()

	if err := deps.runCLI(context.Background(), mgr, args); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 1
	}
	return 0
}
