// Package main provides natsctl - a CLI tool for managing NATS JetStream resources.
package main

import (
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
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

// hasHelpFlag reports whether the only argument is a help flag.
func hasHelpFlag(args []string) bool {
	if len(args) != 1 {
		return false
	}
	switch args[0] {
	case "--help", "-h", "help":
		return true
	default:
		return false
	}
}

func run(args []string) error {
	// Global flags (do NOT register --help/-h here, let them pass through to subcommands)
	var (
		natsURL      = flagString("nats-url", getACSEnv("ACS_NATS_SERVERS", "NATS_URL", defaultNatsURL), "NATS server URL(s), comma-separated")
		natsUser     = flagString("user", getACSEnv("ACS_NATS_USER", "NATS_USER", ""), "NATS username")
		natsPassword = flagString("password", getACSEnv("ACS_NATS_PASSWORD", "NATS_PASSWORD", ""), "NATS password")
		natsToken    = flagString("token", getACSEnv("ACS_NATS_TOKEN", "NATS_TOKEN", ""), "NATS authentication token")
		natsCreds    = flagString("creds", getACSEnv("ACS_NATS_CREDS", "NATS_CREDS", ""), "NATS credentials file path")
		natsNKey     = flagString("nkey", getACSEnv("ACS_NATS_NKEY", "NATS_NKEY", ""), "NATS nkey file path")
		showVersion  = flagBool("version", false, "Show version information")
	)

	// Parse flags
	flagParse(args)

	if *showVersion {
		fmt.Printf("natsctl version %s\n", version)
		return nil
	}

	// Handle top-level help: no args, or only --help/-h in the remaining args
	if len(args) == 0 || (len(args) == 1 && hasHelpFlag(args)) {
		printUsage()
		return nil
	}

	// Strip global flags so command dispatch works regardless of where global
	// flags appear on the command line. Unknown flags are preserved for
	// subcommand parsing.
	positional := flagArgs(args)
	if len(positional) == 0 {
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

	switch positional[0] {
	case "consumer":
		return handleConsumerCommand(positional[1:], *natsURL, opts)
	case "help":
		printUsage()
		return nil
	default:
		return fmt.Errorf("unknown command: %s", positional[0])
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
		fmt.Printf("Are you sure you want to delete consumer %q from stream %q? [y/N]: ", consumerName, streamName)
		var response string
		if _, err := fmt.Scanln(&response); err != nil {
			return fmt.Errorf("failed to read confirmation: %w", err)
		}
		response = strings.ToLower(strings.TrimSpace(response))
		if response != "y" && response != "yes" {
			fmt.Println("Cancelled")
			return nil
		}
	}

	// Connect to NATS
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

	// Delete consumer
	if err := js.DeleteConsumer(streamName, consumerName); err != nil {
		return fmt.Errorf("failed to delete consumer %q from stream %q: %w", consumerName, streamName, err)
	}

	fmt.Printf("Consumer %q deleted from stream %q\n", consumerName, streamName)
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
	fmt.Println("  consumer rm <stream> <consumer>   Remove a JetStream consumer")
	fmt.Println("  help                              Show this help message")
}

func printConsumerUsage() {
	fmt.Println("Usage: natsctl consumer <subcommand> [args...]")
	fmt.Println()
	fmt.Println("Subcommands:")
	fmt.Println("  rm <stream> <consumer>   Remove a JetStream consumer")
	fmt.Println("  help                     Show this help message")
}

func printConsumerRemoveUsage() {
	fmt.Println("Usage: natsctl consumer rm [options] <stream> <consumer>")
	fmt.Println()
	fmt.Println("Options:")
	fmt.Println("  -f, --force    Skip confirmation prompt")
	fmt.Println("  -h, --help     Show this help message")
}

// getEnv returns the value of an environment variable or a default.
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// getACSEnv returns the value of an ACS-prefixed environment variable.
// For backward compatibility, it also checks the legacy non-prefixed name.
func getACSEnv(acsKey, legacyKey, defaultValue string) string {
	if value := os.Getenv(acsKey); value != "" {
		return value
	}
	if legacyKey != "" {
		if value := os.Getenv(legacyKey); value != "" {
			return value
		}
	}
	return defaultValue
}

// ---- flag helpers to avoid flag package conflicts ----

var (
	flagStrings = make(map[string]*string)
	flagBools   = make(map[string]*bool)
)

// flagString registers a string flag and returns a pointer to its value.
func flagString(name, value, usage string) *string {
	p := &value
	flagStrings[name] = p
	return p
}

// flagBool registers a bool flag and returns a pointer to its value.
func flagBool(name string, value bool, usage string) *bool {
	p := &value
	flagBools[name] = p
	return p
}

// flagParse parses args using the registered flags.
func flagParse(args []string) {
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "-") {
			continue
		}

		// Handle --name=value
		name := arg
		var explicitValue string
		if idx := strings.Index(arg, "="); idx >= 0 {
			name = arg[:idx]
			explicitValue = arg[idx+1:]
		}

		// Strip leading dashes
		name = strings.TrimLeft(name, "-")

		// Handle boolean flags like --version or -v
		if p, ok := flagBools[name]; ok {
			*p = true
			continue
		}

		// Handle short bool flags (single char)
		if len(name) == 1 {
			if p, ok := flagBools[name]; ok {
				*p = true
				continue
			}
		}

		// Handle string flags
		if p, ok := flagStrings[name]; ok {
			if explicitValue != "" {
				*p = explicitValue
			} else if i+1 < len(args) {
				*p = args[i+1]
				i++
			}
			continue
		}

		// Handle short string flags (single char)
		if len(name) == 1 {
			if p, ok := flagStrings[name]; ok {
				if i+1 < len(args) {
					*p = args[i+1]
					i++
				}
				continue
			}
		}
	}
}

// flagArgs returns the positional (non-flag) arguments from the command line.
func flagArgs(args []string) []string {
	var positional []string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "-") {
			positional = append(positional, arg)
			continue
		}

		// Handle --name=value
		name := arg
		if idx := strings.Index(arg, "="); idx >= 0 {
			name = arg[:idx]
		}
		name = strings.TrimLeft(name, "-")

		// If this is a known flag, skip its value if it was passed as a separate arg.
		if _, ok := flagBools[name]; ok {
			continue
		}
		if _, ok := flagStrings[name]; ok {
			if !strings.Contains(arg, "=") && i+1 < len(args) {
				i++
			}
			continue
		}

		// Unknown flag: preserve it for subcommand parsing.
		positional = append(positional, arg)
	}
	return positional
}
