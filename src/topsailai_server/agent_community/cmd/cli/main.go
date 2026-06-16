// Package main is the entry point for the ACS CLI terminal.
package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/chzyer/readline"
	"github.com/topsailai/agent-community/internal/nats"
)

const (
	defaultAPIBase     = "http://localhost:7370"
	defaultNATSServers = "nats://localhost:4222"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "cli failed: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	// Parse flags.
	var (
		apiBase     = flag.String("api-base", getEnv("ACS_SERVER_API_BASE", defaultAPIBase), "ACS server API base URL")
		natsURL     = flag.String("nats-url", getEnv("ACS_NATS_SERVERS", defaultNATSServers), "NATS server URL(s)")
		noColorFlag = flag.Bool("no-color", false, "Disable ANSI colors")
		memberID    = flag.String("member-id", getEnv("ACS_CLI_MEMBER_ID", "cli-user"), "Member ID for this CLI session")
		memberName  = flag.String("member-name", getEnv("ACS_CLI_MEMBER_NAME", "CLI User"), "Member name for this CLI session")
	)
	flag.Parse()

	// Initialize color support.
	initColor(os.Args)
	if *noColorFlag {
		noColor = true
	}

	// Print banner.
	printBanner()
	fmt.Printf("API Base:   %s\n", *apiBase)
	fmt.Printf("NATS:       %s\n", *natsURL)
	fmt.Printf("User:       %s (%s)\n", *memberName, *memberID)
	fmt.Println()
	fmt.Println("Type /help for available commands")
	fmt.Println()

	// Initialize components.
	apiClient := NewAPIClient(*apiBase)

	natsManager := NewNATSManager(apiClient, func(event *nats.PendingPublishMessage) {
		// Default event handler: display events when not in chat mode.
		fmt.Println(formatGenericEvent(event.Type, event.Action, event.GroupID))
	})

	// Attempt NATS connection (non-fatal).
	if err := natsManager.Connect(); err != nil {
		printWarning(fmt.Sprintf("NATS not available: %v", err))
		printInfo("HTTP polling will be used for real-time updates.")
	}

	chatMode := NewChatMode(apiClient, natsManager)

	// Create readline instance with auto-completion.
	rl, err := readline.NewEx(&readline.Config{
		Prompt:       ps1Normal(*memberName),
		AutoComplete: newNormalCompleter(),
	})
	if err != nil {
		return fmt.Errorf("failed to create readline: %w", err)
	}
	defer rl.Close()

	state := &CLIState{
		apiClient:   apiClient,
		natsManager: natsManager,
		chatMode:    chatMode,
		userID:      *memberID,
		userName:    *memberName,
		running:     true,
		rl:          rl,
	}

	// Main command loop.
	for state.running {
		line, err := state.rl.Readline()
		if err != nil {
			// EOF or interrupt.
			break
		}

		if err := DispatchCommand(line, state); err != nil {
			printError(err.Error())
		}
	}

	// Cleanup.
	printInfo("Goodbye!")
	chatMode.LeaveChat()
	natsManager.Close()
	return nil
}

// getEnv returns the value of an environment variable or a default.
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
