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
		memberName  = flag.String("member-name", getEnv("ACS_CLI_MEMBER_NAME", "cli_user"), "Member name for this CLI session")
		apiKey      = flag.String("api-key", getEnv("ACS_API_KEY", ""), "API key token (ak-{id}.{secret})")
		sessionKey  = flag.String("session-key", getEnv("ACS_SESSION_KEY", ""), "Login session key")
	)
	flag.Parse()

	// Initialize color support.
	initColor(os.Args)
	if *noColorFlag {
		noColor = true
	}

	// Initialize components.
	apiClient := NewAPIClient(*apiBase)

	natsManager := NewNATSManager(apiClient, func(event *nats.PendingPublishMessage) {
		// Default event handler: display events when not in chat mode.
		promptPrintln(formatGenericEvent(event.Type, event.Action, event.GroupID))
	})

	// Attempt NATS connection (non-fatal).
	if err := natsManager.Connect(); err != nil {
		printWarning(fmt.Sprintf("NATS not available: %v", err))
		printInfo("HTTP polling will be used for real-time updates.")
	}

	chatMode := NewChatMode(apiClient, natsManager)

	// Determine initial authentication method.
	authMethod, credential := resolveInitialAuth(*apiKey, *sessionKey)
	if credential != "" {
		apiClient.SetAuthMethod(authMethod, credential)
	}

	// Initial userID is empty until authenticated.
	userID := ""
	userName := *memberName
	accountRole := ""

	// If authenticated, fetch the current account so the prompt and group
	// membership checks use the real account identity instead of CLI defaults.
	if apiClient.IsAuthenticated() {
		meResp, err := apiClient.GetMe()
		if err == nil {
			var me map[string]interface{}
			if err := meResp.GetData(&me); err == nil {
				if id, ok := me["account_id"].(string); ok && id != "" {
					userID = id
				}
				if name, ok := me["account_name"].(string); ok && name != "" {
					userName = name
				}
				if role, ok := me["role"].(string); ok && role != "" {
					accountRole = role
				}
			}
		}
	}

	// When we know the authenticated account, use it as the member identity
	// for group operations. Otherwise fall back to CLI defaults.
	activeMemberID := *memberID
	activeMemberName := *memberName
	if userID != "" {
		activeMemberID = userID
		activeMemberName = userName
	}

	// Create readline instance with auto-completion.
	rl, err := readline.NewEx(&readline.Config{
		Prompt:       ps1Normal(userName, userID, accountRole),
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
		userID:      userID,
		userName:    userName,
		memberID:    activeMemberID,
		memberName:  activeMemberName,
		accountRole: accountRole,
		authMethod:  authMethod,
		apiKey:      *apiKey,
		sessionKey:  *sessionKey,
		running:     true,
		rl:          rl,
	}
	// Register state with the prompt manager so output keeps the active prompt at the bottom.
	setPromptState(state)

	// Print banner after registering state so prompt-aware output works.
	printBanner()
	promptPrintf("API Base:   %s\n", *apiBase)
	promptPrintf("NATS:       %s\n", *natsURL)
	if state.userID != "" {
		promptPrintf("User:       %s (%s) [id=%s]\n", state.userName, state.memberID, state.userID)
	} else {
		promptPrintf("User:       %s (%s)\n", state.userName, state.memberID)
	}
	if authMethod != "" {
		promptPrintf("Auth:       %s\n", authMethod)
	} else {
		promptPrintln("Auth:       anonymous (use /login)")
	}
	promptPrintln()
	promptPrintln("Type /help for available commands")
	promptPrintln()
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

// resolveInitialAuth selects the initial authentication method from flags.
// Session key takes precedence over API key when both are provided.
func resolveInitialAuth(apiKey, sessionKey string) (AuthMethod, string) {
	if sessionKey != "" {
		return AuthMethodSession, sessionKey
	}
	if apiKey != "" {
		return AuthMethodAPIKey, apiKey
	}
	return "", ""
}

// getEnv returns the value of an environment variable or a default.
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
