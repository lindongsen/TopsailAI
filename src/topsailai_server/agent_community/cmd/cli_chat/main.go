// Package main implements the ACS group-only chat CLI.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"

	"github.com/chzyer/readline"
)

type config struct {
	apiBase    string
	natsURL    string
	apiKey     string
	sessionKey string
	noColor    bool
	showHelp   bool
}

func main() {
	cfg := parseFlags()
	if cfg.showHelp {
		printUsage()
		os.Exit(0)
	}
	if cfg.noColor || os.Getenv("NO_COLOR") != "" {
		DisableColors()
	}
	ctx := context.Background()
	app, err := newAppFromConfig(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to initialize CLI: %v\n", err)
		os.Exit(1)
	}
	if err := app.Authenticate(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if err := app.Run(ctx); err != nil {
		if err == errExit {
			os.Exit(0)
		}
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

func parseFlags() config {
	var cfg config
	flag.StringVar(&cfg.apiBase, "api-base", getEnv("ACS_SERVER_API_BASE", "http://localhost:7370"), "ACS server API base URL")
	flag.StringVar(&cfg.natsURL, "nats-url", getEnv("ACS_NATS_SERVERS", ""), "NATS server URL (optional)")
	flag.StringVar(&cfg.apiKey, "api-key", "", "API key token in the form ak-{id}.{secret} (also ACS_API_KEY env)")
	flag.StringVar(&cfg.sessionKey, "session-key", "", "Login session key (also ACS_SESSION_KEY env)")
	flag.BoolVar(&cfg.noColor, "no-color", false, "Disable colored output")
	flag.BoolVar(&cfg.showHelp, "help", false, "Show help")
	flag.Parse()

	if cfg.apiKey == "" {
		cfg.apiKey = getEnv("ACS_API_KEY", "")
	}
	if cfg.sessionKey == "" {
		cfg.sessionKey = getEnv("ACS_SESSION_KEY", "")
	}
	return cfg
}

func newAppFromConfig(cfg config) (*App, error) {
	client := NewClient(cfg.apiBase)
	switch {
	case cfg.sessionKey != "":
		client.SetSessionKey(cfg.sessionKey)
	case cfg.apiKey != "":
		client.SetAPIKey(cfg.apiKey)
	}
	var natsClient *NATSClient
	if cfg.natsURL != "" {
		natsClient = NewNATSClient(cfg.natsURL)
	}
	completer := NewCompleter()
	display := NewDisplay(cfg.noColor)
	prompt := NewPromptManager("")
	cfgRL := &readline.Config{
		Prompt:          prompt.Prompt(),
		AutoComplete:    completer,
		InterruptPrompt: "^C",
		EOFPrompt:       "exit",
	}
	rl, err := readline.NewEx(cfgRL)
	if err != nil {
		return nil, err
	}
	return NewApp(client, rl, completer, display, prompt, natsClient), nil
}

func printUsage() {
	fmt.Println(`ACS Chat CLI

Usage:
  cli_chat [options]

Options:
  --api-base string    ACS server API base URL (default http://localhost:7370)
  --nats-url string    NATS server URL for real-time events (optional)
  --api-key string     API key token in the form ak-{id}.{secret}
  --session-key string Login session key
  --no-color           Disable colored output
  --help               Show this help

Authentication:
  Credentials can be provided via flags or environment variables.
  --api-key / ACS_API_KEY          API key token (ak-{id}.{secret})
  --session-key / ACS_SESSION_KEY  Login session key
  If neither is provided, the CLI prompts interactively.

Commands:
  /group list              List groups
  /group create            Create a group (interactive)
  /chat <group_id>         Enter a group chat
  /member list             List members of current group
  /member add              Add a member to current group (interactive)
  /group leave             Leave current group chat
  /help                    Show help
  exit | quit              Exit the CLI`)
}
