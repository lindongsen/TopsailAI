// Package main provides command parsing and dispatch for the ACS chat CLI.
package main

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

var errExit = errors.New("exit")

// Input represents a parsed CLI command.
type Input struct {
	Name string
	Args []string
}

// Suggestion returns a canonical command suggestion for errors.
func (in Input) Suggestion() string {
	switch in.Name {
	case "group":
		if len(in.Args) > 0 {
			return fmt.Sprintf("/group %s", in.Args[0])
		}
		return "/group list"
	case "chat":
		return "/chat <group_id>"
	case "member":
		if len(in.Args) > 0 {
			return fmt.Sprintf("/member %s", in.Args[0])
		}
		return "/member list"
	case "help":
		return "/help"
	case "exit", "quit":
		return "exit"
	default:
		return "/help"
	}
}

// ParseInput parses a raw input line into a command and arguments.
func ParseInput(line string) Input {
	line = strings.TrimSpace(line)
	if line == "" {
		return Input{}
	}
	line = expandAlias(line)
	if line == "exit" || line == "quit" {
		return Input{Name: "exit"}
	}
	if line == "help" {
		return Input{Name: "help"}
	}
	if !strings.HasPrefix(line, "/") {
		return Input{Name: line}
	}
	parts := strings.Fields(line[1:])
	if len(parts) == 0 {
		return Input{}
	}
	name := parts[0]
	args := parts[1:]
	// Handle legacy colon style: /group:list -> /group list
	if strings.Contains(name, ":") {
		parts := strings.SplitN(name, ":", 2)
		name = parts[0]
		if len(parts) > 1 && parts[1] != "" {
			args = append([]string{parts[1]}, args...)
		}
	}
	return Input{Name: name, Args: args}
}

// Dispatch routes a parsed command to the appropriate handler.
func Dispatch(ctx context.Context, app *App, input Input) error {
	switch input.Name {
	case "group":
		return handleGroup(ctx, app, input.Args)
	case "chat":
		return handleChat(ctx, app, input.Args)
	case "member":
		return handleMember(ctx, app, input.Args)
	case "help":
		printHelp(app)
		return nil
	case "exit", "quit":
		return errExit
	default:
		return fmt.Errorf("unknown command: %s", input.Name)
	}
}

func handleGroup(ctx context.Context, app *App, args []string) error {
	if len(args) == 0 {
		return app.ListGroups(ctx)
	}
	switch args[0] {
	case "list":
		return app.ListGroups(ctx)
	case "create":
		return app.CreateGroup(ctx, args[1:])
	case "leave":
		return app.LeaveCurrentGroup(ctx)
	default:
		return fmt.Errorf("unknown group subcommand: %s", args[0])
	}
}

// parseGroupCreateArgs parses arguments for /group create.
// It supports both positional and flag styles, and mixed usage where flags win.
// If no name can be resolved, needInteractive is true.
func parseGroupCreateArgs(args []string) (name, contextText, key string, needInteractive bool, err error) {
	if len(args) == 0 {
		return "", "", "", true, nil
	}

	var positional []string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "--") {
			positional = append(positional, arg)
			continue
		}

		var flagName, flagValue string
		if idx := strings.Index(arg, "="); idx >= 0 {
			flagName = arg[2:idx]
			flagValue = arg[idx+1:]
		} else {
			flagName = arg[2:]
			if i+1 >= len(args) {
				return "", "", "", false, fmt.Errorf("flag %q requires a value", arg)
			}
			flagValue = args[i+1]
			i++
		}

		switch flagName {
		case "name":
			name = flagValue
		case "context":
			contextText = flagValue
		case "key":
			key = flagValue
		default:
			return "", "", "", false, fmt.Errorf("unknown flag: --%s", flagName)
		}
	}

	// Fill remaining fields from positional args in order: name, context, key.
	if name == "" && len(positional) > 0 {
		name = positional[0]
		positional = positional[1:]
	}
	if contextText == "" && len(positional) > 0 {
		contextText = positional[0]
		positional = positional[1:]
	}
	if key == "" && len(positional) > 0 {
		key = positional[0]
	}

	if name == "" {
		needInteractive = true
	}
	return name, contextText, key, needInteractive, nil
}

func handleChat(ctx context.Context, app *App, args []string) error {
	if len(args) == 0 {
		groupID, err := PromptString("Group ID: ")
		if err != nil {
			return err
		}
		return app.EnterChat(ctx, groupID)
	}
	return app.EnterChat(ctx, args[0])
}

func handleMember(ctx context.Context, app *App, args []string) error {
	if len(args) == 0 {
		return app.ListMembers(ctx)
	}
	switch args[0] {
	case "list":
		return app.ListMembers(ctx)
	case "add":
		return app.AddMember(ctx, args[1:])
	default:
		return fmt.Errorf("unknown member subcommand: %s", args[0])
	}
}

func printHelp(app *App) {
	fmt.Println(app.display.Info("ACS Chat CLI Commands"))
	fmt.Println()
	fmt.Println("  /group list              List groups")
	fmt.Println("  /group create [name] [context] [key]")
	fmt.Println("  /group create --name <name> [--context <context>] [--key <key>]")
	fmt.Println("                           Create a new group")
	fmt.Println("  /chat <group_id>         Enter a group chat")
	fmt.Println("  /member list             List members of current group")
	fmt.Println("  /member add <id> <name> <type>")
	fmt.Println("                           Add a member to current group")
	fmt.Println("  /group leave             Leave current group chat")
	fmt.Println("  /help                    Show this help")
	fmt.Println("  exit | quit              Exit the CLI")
}
