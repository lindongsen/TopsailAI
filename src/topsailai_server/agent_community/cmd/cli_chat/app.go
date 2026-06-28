// Package main provides the application state and top-level command handlers for the ACS chat CLI.
package main

import (
	"context"
	"fmt"
	"io"
	"strings"

	"github.com/chzyer/readline"
)
type App struct {
	client       *Client
	rl           *readline.Instance
	prompt       *PromptManager
	display      *Display
	completer    *Completer
	nats         *NATSClient
	statusBar    *StatusBar
	accountID    string
	accountName  string
	currentGroup *Group
	members      []Member
}

// NewApp creates a new App instance.
func NewApp(client *Client, rl *readline.Instance, completer *Completer, display *Display, prompt *PromptManager, nats *NATSClient) *App {
	return &App{
		client:    client,
		rl:        rl,
		prompt:    prompt,
		display:   display,
		completer: completer,
		nats:      nats,
		statusBar: NewStatusBar(0),
	}
}

// Authenticate resolves credentials and verifies them with the server.
func (app *App) Authenticate(ctx context.Context) error {
	return app.authenticate(ctx)
}

// Run starts the main REPL loop.
func (app *App) Run(ctx context.Context) error {
	if err := app.authenticate(ctx); err != nil {
		return err
	}
	fmt.Println(app.display.Info(fmt.Sprintf("Welcome, %s (%s)", app.accountName, app.accountID)))
	printGlobalHelp(app)
	for {
		app.rl.SetPrompt(app.prompt.String())
		line, err := app.rl.Readline()
		if err != nil {
			if err == readline.ErrInterrupt {
				continue
			}
			if err == io.EOF {
				return nil
			}
			return err
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		input := ParseInput(line)
		if input.Name == "" {
			continue
		}
		if err := Dispatch(ctx, app, input); err != nil {
			if err == errExit {
				return nil
			}
			app.display.PrintError(err, input.Suggestion())
		}
	}
}

func (app *App) authenticate(ctx context.Context) error {
	// If a credential was already configured from flags/environment, verify it.
	if app.client.sessionKey != "" {
		return app.verifySessionKey(ctx)
	}
	if app.client.apiKey != "" {
		return app.verifyAPIKey(ctx)
	}

	fmt.Println(app.display.Info("Please choose an authentication method:"))
	fmt.Println("  1) API key")
	fmt.Println("  2) Session key")
	fmt.Println("  3) Login name and password")
	for {
		choice, err := PromptString("Method (1/2/3): ")
		if err != nil {
			return err
		}
		switch strings.TrimSpace(choice) {
		case "1":
			return app.promptAPIKey(ctx)
		case "2":
			return app.promptSessionKey(ctx)
		case "3":
			return app.promptLogin(ctx)
		default:
			fmt.Println(app.display.Warning("Invalid choice. Please enter 1, 2, or 3."))
		}
	}
}

func (app *App) verifyAPIKey(ctx context.Context) error {
	acc, err := app.client.GetMe(ctx)
	if err != nil {
		return fmt.Errorf("API key authentication failed: %w", err)
	}
	app.setAccount(acc)
	return nil
}

func (app *App) verifySessionKey(ctx context.Context) error {
	acc, err := app.client.GetMe(ctx)
	if err != nil {
		return fmt.Errorf("session key authentication failed: %w", err)
	}
	app.setAccount(acc)
	return nil
}

func (app *App) promptAPIKey(ctx context.Context) error {
	apiKey, err := PromptString("API key (ak-{id}.{secret}): ")
	if err != nil {
		return err
	}
	app.client.SetAPIKey(apiKey)
	return app.verifyAPIKey(ctx)
}

func (app *App) promptSessionKey(ctx context.Context) error {
	sessionKey, err := PromptString("Session key: ")
	if err != nil {
		return err
	}
	app.client.SetSessionKey(sessionKey)
	return app.verifySessionKey(ctx)
}

func (app *App) promptLogin(ctx context.Context) error {
	loginName, err := PromptString("Login name: ")
	if err != nil {
		return err
	}
	loginPassword, err := PromptPassword("Password: ")
	if err != nil {
		return err
	}
	resp, _, err := app.client.Login(ctx, loginName, loginPassword)
	if err != nil {
		return fmt.Errorf("login failed: %w", err)
	}
	app.accountID = resp.AccountID
	app.accountName = resp.AccountID
	app.prompt.SetUser(resp.AccountID)
	return nil
}

func (app *App) setAccount(acc *Account) {
	app.accountID = acc.AccountID
	app.accountName = acc.AccountName
	app.prompt.SetUser(acc.AccountName)
}

// ListGroups lists groups visible to the authenticated account.
func (app *App) ListGroups(ctx context.Context) error {
	groups, err := app.client.ListGroups(ctx)
	if err != nil {
		return err
	}
	fmt.Println(app.display.Groups(groups))
	return nil
}

// CreateGroup creates a new group.
func (app *App) CreateGroup(ctx context.Context, args []string) error {
	name, groupContext, key, needInteractive, err := parseGroupCreateArgs(args)
	if err != nil {
		return err
	}
	if needInteractive {
		name, groupContext, key, err = collectGroupCreateArgsInteractive()
		if err != nil {
			return err
		}
	}
	group, err := app.client.CreateGroup(ctx, name, groupContext, key)
	if err != nil {
		return err
	}
	fmt.Println(app.display.Group(group))
	return nil
}

// LeaveCurrentGroup leaves the current group chat.
func (app *App) LeaveCurrentGroup(ctx context.Context) error {
	if app.currentGroup == nil {
		return fmt.Errorf("not in a group chat")
	}
	if err := app.client.LeaveGroup(ctx, app.currentGroup.GroupID, app.accountID); err != nil {
		return err
	}
	fmt.Println(app.display.Info(fmt.Sprintf("Left group %s", app.currentGroup.GroupID)))
	app.currentGroup = nil
	app.members = nil
	app.prompt.SetGroup("")
	app.completer.SetMembers(nil)
	if app.statusBar != nil {
		app.statusBar.Update(nil)
	}
	return nil
}

// ListMembers lists members of the current group.
func (app *App) ListMembers(ctx context.Context) error {
	if app.currentGroup == nil {
		return fmt.Errorf("not in a group chat")
	}
	members, err := app.client.ListMembers(ctx, app.currentGroup.GroupID)
	if err != nil {
		return err
	}
	fmt.Println(app.display.Members(members))
	return nil
}

// AddMember adds a member to the current group.
func (app *App) AddMember(ctx context.Context, args []string) error {
	if app.currentGroup == nil {
		return fmt.Errorf("not in a group chat")
	}
	memberID, memberName, memberType, iface, err := collectAddMemberArgs(args)
	if err != nil {
		return err
	}
	member, err := app.client.AddMember(ctx, app.currentGroup.GroupID, memberID, memberName, memberType, iface)
	if err != nil {
		return err
	}
	fmt.Println(app.display.Member(member))
	return nil
}

// handleMemberAddInline parses inline args for /member add inside chat mode.
func (app *App) handleMemberAddInline(ctx context.Context, args string) error {
	parts := strings.Fields(args)
	if err := app.AddMember(ctx, parts); err != nil {
		return err
	}
	_ = app.refreshMembers(ctx)
	return nil
}

func printGlobalHelp(app *App) {
	fmt.Println(app.display.Info("ACS Chat CLI"))
	fmt.Println()
	fmt.Println("  /group list              List groups")
	fmt.Println("  /group create [name] [context] [key]")
	fmt.Println("                           Create a new group")
	fmt.Println("  /chat <group_id>         Enter a group chat")
	fmt.Println("  /help                    Show this help")
	fmt.Println("  exit | quit              Exit the CLI")
}
