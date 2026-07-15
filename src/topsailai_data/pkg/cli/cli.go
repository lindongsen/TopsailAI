// Package cli implements the command-line interface for topsailai_data.
//
// It uses github.com/spf13/pflag to support POSIX-style flag placement, so
// flags may appear before or after positional arguments.
package cli

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/spf13/pflag"
	"github.com/topsailai/topsailai_data/pkg/manager"
)

// Command represents a CLI subcommand.
type Command struct {
	Name  string
	Usage string
	Run   func(ctx context.Context, mgr *manager.Manager, args []string) error
}

// Run parses the command line and dispatches to the appropriate subcommand.
func Run(ctx context.Context, mgr *manager.Manager, args []string) error {
	if len(args) == 0 {
		return runInteractive(ctx, mgr)
	}

	name := args[0]
	if name == "-h" || name == "--help" || name == "help" {
		printUsage(os.Stdout)
		return nil
	}

	commands := registeredCommands()
	for _, cmd := range commands {
		if cmd.Name == name {
			return cmd.Run(ctx, mgr, args[1:])
		}
	}

	return fmt.Errorf("unknown command %q", name)
}

func registeredCommands() []Command {
	return []Command{
		{Name: "create", Usage: "create <object> [--classify dir1/dir2/...] [--tag tag1,tag2] [--from file|archive]", Run: runCreate},
		{Name: "show", Usage: "show <id>", Run: runShow},
		{Name: "list", Usage: "list [--tag tag] [--include-deleted]", Run: runList},
		{Name: "search", Usage: "search <query>", Run: runSearch},
		{Name: "tag", Usage: "tag add <id> <tag> | tag remove <id> <tag>", Run: runTag},
		{Name: "move", Usage: "move <id> <new-classify...>", Run: runMove},
		{Name: "delete", Usage: "delete <id>", Run: runDelete},
		{Name: "recover", Usage: "recover <id>", Run: runRecover},
		{Name: "gc", Usage: "gc [--dry-run] [--status creating|deleted|ceased]", Run: runGC},
		{Name: "get", Usage: "get <id> <file>", Run: runGet},
		{Name: "get-archive", Usage: "get-archive <id>", Run: runGetArchive},
		{Name: "put", Usage: "put <id> <file>", Run: runPut},
		{Name: "put-archive", Usage: "put-archive <id> <archive>", Run: runPutArchive},
	}
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "Usage: topsailai_data <command> [arguments]")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Commands:")
	for _, cmd := range registeredCommands() {
		fmt.Fprintf(w, "  %-15s %s\n", cmd.Name, cmd.Usage)
	}
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Environment variables:")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_ROOT                  root directory for local storage")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_METADATA_ADAPTER      metadata adapter name (default: local)")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER   actual-data adapter name (default: local)")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_READ_LOCK             acquire locks on read operations (default: 0)")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_INCLUDE_DELETED       include deleted/ceased in list/search (default: false)")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_CEASED_RETENTION_DAYS retention for ceased metadata (default: 30)")
	fmt.Fprintln(w, "  TOPSAILAI_DATA_LOG_LEVEL             log level (default: INFO)")
}

// newFlagSet creates a flag set with common settings for a subcommand.
func newFlagSet(name string) *pflag.FlagSet {
	fs := pflag.NewFlagSet(name, pflag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

// splitList splits a comma-separated list and trims whitespace from each item.
func splitList(s string) []string {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// requireArgs returns an error if the number of arguments is outside the
// expected range. min and max are inclusive; use -1 for max to allow unlimited.
func requireArgs(args []string, min, max int) error {
	if len(args) < min {
		return fmt.Errorf("expected at least %d argument(s), got %d", min, len(args))
	}
	if max >= 0 && len(args) > max {
		return fmt.Errorf("expected at most %d argument(s), got %d", max, len(args))
	}
	return nil
}

// runInteractive provides a minimal interactive prompt when no command is given.
func runInteractive(ctx context.Context, mgr *manager.Manager) error {
	fmt.Println("topsailai_data interactive mode")
	fmt.Println("Type 'help' for available commands or 'exit' to quit.")
	for {
		fmt.Print("> ")
		var line string
		if _, err := fmt.Scanln(&line); err != nil {
			if err == io.EOF {
				fmt.Println()
				return nil
			}
			return fmt.Errorf("read input: %w", err)
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if line == "exit" || line == "quit" {
			return nil
		}
		parts := strings.Fields(line)
		if err := Run(ctx, mgr, parts); err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
		}
	}
}
