// Package main provides natsctl - a CLI tool for managing NATS JetStream resources.
package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/nats-io/nats.go"
)

const (
	version         = "0.1.0"
	defaultNatsURL  = "nats://localhost:4222"
	defaultNatsName = "natsctl"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

// hasHelpFlag checks if --help or -h appears anywhere in the remaining args.
func hasHelpFlag(args []string) bool {
	for _, arg := range args {
		if arg == "--help" || arg == "-h" {
			return true
		}
	}
	return false
}

func run() error {
	// Global flags (do NOT register --help/-h here, let them pass through to subcommands)
	var (
		natsURL      = flagString("nats-url", getEnv("NATS_URL", defaultNatsURL), "NATS server URL(s), comma-separated")
		natsUser     = flagString("user", getEnv("NATS_USER", ""), "NATS username")
		natsPassword = flagString("password", getEnv("NATS_PASSWORD", ""), "NATS password")
		natsToken    = flagString("token", getEnv("NATS_TOKEN", ""), "NATS authentication token")
		natsCreds    = flagString("creds", getEnv("NATS_CREDS", ""), "NATS credentials file path")
		natsNKey     = flagString("nkey", getEnv("NATS_NKEY", ""), "NATS nkey file path")
		showVersion  = flagBool("version", false, "Show version information")
	)

	// Parse flags
	flagParse()

	if *showVersion {
		fmt.Printf("natsctl version %s\n", version)
		return nil
	}

	args := flagArgs()

	// Handle top-level help: no args, or only --help/-h in the remaining args
	if len(args) == 0 || (len(args) == 1 && hasHelpFlag(args)) {
		printUsage()
		return nil
	}

	// Build NATS connection options
	opts := []nats.Option{
		nats.Name(defaultNatsName),
	}

	if *natsUser != "" && *natsPassword != "" {
		opts = append(opts, nats.UserInfo(*natsUser, *natsPassword))
	}
	if *natsToken != "" {
		opts = append(opts, nats.Token(*natsToken))
	}
	if *natsCreds != "" {
		opts = append(opts, nats.UserCredentials(*natsCreds))
	}
	if *natsNKey != "" {
		opts = append(opts, nats.UserCredentials(*natsNKey))
	}

	switch args[0] {
	case "consumer":
		return handleConsumerCommand(args[1:], *natsURL, opts)
	case "help":
		printUsage()
		return nil
	default:
		return fmt.Errorf("unknown command: %s", args[0])
	}
}

func handleConsumerCommand(args []string, natsURL string, opts []nats.Option) error {
	if len(args) == 0 {
		printConsumerUsage()
		return fmt.Errorf("consumer subcommand required")
	}

	switch args[0] {
	case "rm", "remove", "delete", "del":
		return handleConsumerRemove(args[1:], natsURL, opts)
	case "help":
		printConsumerUsage()
		return nil
	default:
		return fmt.Errorf("unknown consumer subcommand: %s", args[0])
	}
}

func handleConsumerRemove(args []string, natsURL string, opts []nats.Option) error {
	// Parse local flags for rm command
	var force bool
	newArgs := make([]string, 0, len(args))
	for i := 0; i < len(args); i++ {
		if args[i] == "-f" || args[i] == "--force" {
			force = true
		} else if args[i] == "--help" || args[i] == "-h" {
			printConsumerRemoveUsage()
			return nil
		} else {
			newArgs = append(newArgs, args[i])
		}
	}

	if len(newArgs) < 2 {
		printConsumerRemoveUsage()
		return fmt.Errorf("stream and consumer names are required")
	}

	streamName := newArgs[0]
	consumerName := newArgs[1]

	// Confirm deletion unless force flag is set
	if !force {
		fmt.Printf("Are you sure you want to delete consumer '%s' from stream '%s'? [y/N]: ", consumerName, streamName)
		reader := bufio.NewReader(os.Stdin)
		response, err := reader.ReadString('\n')
		if err != nil {
			return fmt.Errorf("failed to read confirmation: %w", err)
		}
		response = strings.TrimSpace(strings.ToLower(response))
		if response != "y" && response != "yes" {
			fmt.Println("Operation cancelled.")
			return nil
		}
	}

	// Connect to NATS
	fmt.Printf("Connecting to NATS at %s...\n", natsURL)
	nc, err := nats.Connect(natsURL, opts...)
	if err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer nc.Close()

	// Get JetStream context
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	// Delete the consumer
	fmt.Printf("Deleting consumer '%s' from stream '%s'...\n", consumerName, streamName)
	err = js.DeleteConsumer(streamName, consumerName)
	if err != nil {
		if err == nats.ErrConsumerNotFound {
			return fmt.Errorf("consumer '%s' not found in stream '%s'", consumerName, streamName)
		}
		return fmt.Errorf("failed to delete consumer: %w", err)
	}

	fmt.Printf("Successfully deleted consumer '%s' from stream '%s'\n", consumerName, streamName)
	return nil
}

func printUsage() {
	fmt.Println("natsctl - A CLI tool for managing NATS JetStream resources")
	fmt.Println()
	fmt.Println("Usage: natsctl [global-options] <command> [subcommand] [args...]")
	fmt.Println()
	fmt.Println("Global Options:")
	fmt.Println("  --nats-url <url>     NATS server URL(s), comma-separated (default: nats://localhost:4222)")
	fmt.Println("  --user <user>        NATS username")
	fmt.Println("  --password <pass>    NATS password")
	fmt.Println("  --token <token>      NATS authentication token")
	fmt.Println("  --creds <path>       NATS credentials file path")
	fmt.Println("  --nkey <path>        NATS nkey file path")
	fmt.Println("  --version            Show version information")
	fmt.Println("  --help, -h           Show this help message")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  consumer             Manage NATS consumers")
	fmt.Println("  help                 Show this help message")
	fmt.Println()
	fmt.Println("Examples:")
	fmt.Println("  natsctl consumer rm acs_pending_messages pending-message-consumer -f")
	fmt.Println("  natsctl --nats-url nats://localhost:4222 consumer rm mystream myconsumer --force")
	fmt.Println("  natsctl --user admin --password secret consumer rm mystream myconsumer")
}

func printConsumerUsage() {
	fmt.Println("Usage: natsctl consumer <subcommand> [args...]")
	fmt.Println()
	fmt.Println("Subcommands:")
	fmt.Println("  rm, remove, delete, del   Delete a consumer from a stream")
	fmt.Println("  help                      Show this help message")
	fmt.Println()
	fmt.Println("Use 'natsctl consumer rm --help' for more information.")
}

func printConsumerRemoveUsage() {
	fmt.Println("Usage: natsctl consumer rm <stream> <consumer> [options]")
	fmt.Println()
	fmt.Println("Delete a consumer from a NATS JetStream stream.")
	fmt.Println()
	fmt.Println("Arguments:")
	fmt.Println("  stream    The name of the JetStream stream")
	fmt.Println("  consumer  The name of the consumer to delete")
	fmt.Println()
	fmt.Println("Options:")
	fmt.Println("  -f, --force    Skip confirmation prompt")
	fmt.Println()
	fmt.Println("Examples:")
	fmt.Println("  natsctl consumer rm acs_pending_messages pending-message-consumer -f")
	fmt.Println("  natsctl consumer rm mystream myconsumer --force")
}

// getEnv returns the value of an environment variable or a default.
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// ---- flag helpers to avoid flag package conflicts ----

var (
	flagStrings = make(map[string]*string)
	flagBools   = make(map[string]*bool)
)

func flagString(name, value, usage string) *string {
	p := new(string)
	*p = value
	flagStrings[name] = p
	return p
}

func flagBool(name string, value bool, usage string) *bool {
	p := new(bool)
	*p = value
	flagBools[name] = p
	return p
}

func flagParse() {
	// We parse manually to avoid conflicts with subcommand args
	args := os.Args[1:]
	var i int
	for i < len(args) {
		arg := args[i]
		if !strings.HasPrefix(arg, "-") {
			break
		}

		// Handle --flag=value
		if strings.HasPrefix(arg, "--") {
			parts := strings.SplitN(arg, "=", 2)
			name := strings.TrimPrefix(parts[0], "--")
			if s, ok := flagStrings[name]; ok {
				if len(parts) == 2 {
					*s = parts[1]
				} else if i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
					*s = args[i+1]
					i++
				}
			} else if b, ok := flagBools[name]; ok {
				*b = true
			}
		} else if strings.HasPrefix(arg, "-") {
			// Handle -h shorthand (but not for help, since we don't register it)
			name := strings.TrimPrefix(arg, "-")
			if b, ok := flagBools[name]; ok {
				*b = true
			}
		}
		i++
	}
}

func flagArgs() []string {
	args := os.Args[1:]
	var result []string
	var i int
	for i < len(args) {
		arg := args[i]
		if !strings.HasPrefix(arg, "-") {
			result = append(result, arg)
			i++
			continue
		}

		// Preserve --help and -h for subcommand handling
		if arg == "--help" || arg == "-h" {
			result = append(result, arg)
			i++
			continue
		}

		// Skip flags and their values
		if strings.HasPrefix(arg, "--") {
			parts := strings.SplitN(arg, "=", 2)
			name := strings.TrimPrefix(parts[0], "--")
			if _, ok := flagStrings[name]; ok {
				if len(parts) == 2 {
					i++
					continue
				} else if i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
					i += 2
					continue
				}
			} else if _, ok := flagBools[name]; ok {
				i++
				continue
			}
		} else if strings.HasPrefix(arg, "-") {
			name := strings.TrimPrefix(arg, "-")
			if _, ok := flagBools[name]; ok {
				i++
				continue
			}
		}
		i++
	}
	return result
}
