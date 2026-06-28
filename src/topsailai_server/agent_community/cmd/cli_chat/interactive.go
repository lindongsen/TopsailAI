// Package main provides interactive input helpers for the ACS chat CLI.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"golang.org/x/term"
)

// PromptString prompts for a string value.
func PromptString(label string) (string, error) {
	fmt.Print(label)
	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadString('\n')
	if err != nil {
		return "", err
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return "", fmt.Errorf("cancelled")
	}
	return line, nil
}

// PromptPassword prompts for a password without echoing input.
func PromptPassword(label string) (string, error) {
	fmt.Print(label)
	bytePassword, err := term.ReadPassword(int(os.Stdin.Fd()))
	fmt.Println()
	if err != nil {
		return "", err
	}
	password := strings.TrimSpace(string(bytePassword))
	if password == "" {
		return "", fmt.Errorf("cancelled")
	}
	return password, nil
}

// PromptOptional prompts for an optional string value.
func PromptOptional(label string) (string, error) {
	fmt.Print(label)
	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

// collectGroupCreateArgsInteractive collects group creation arguments interactively.
func collectGroupCreateArgsInteractive() (name, contextText, key string, err error) {
	name, err = PromptString("Group name: ")
	if err != nil {
		return
	}
	if name == "" {
		err = fmt.Errorf("group name is required")
		return
	}
	contextText, err = PromptOptional("Group context (optional): ")
	if err != nil {
		return
	}
	key, err = PromptOptional("Group key (optional): ")
	if err != nil {
		return
	}
	return
}

// collectAddMemberArgs collects member addition arguments interactively if needed.
// For agent member types (ending in "-agent"), it also prompts for member_interface JSON.
func collectAddMemberArgs(args []string) (memberID, name, memberType string, iface map[string]any, err error) {
	iface = make(map[string]any)
	switch len(args) {
	case 0:
		memberID, err = PromptString("Member ID: ")
		if err != nil {
			return
		}
		name, err = PromptString("Member name: ")
		if err != nil {
			return
		}
		memberType, err = PromptString("Member type (user/worker-agent/manager-agent): ")
		if err != nil {
			return
		}
	case 1:
		memberID = args[0]
		name, err = PromptString("Member name: ")
		if err != nil {
			return
		}
		memberType, err = PromptString("Member type (user/worker-agent/manager-agent): ")
		if err != nil {
			return
		}
	case 2:
		memberID, name = args[0], args[1]
		memberType, err = PromptString("Member type (user/worker-agent/manager-agent): ")
		if err != nil {
			return
		}
	default:
		memberID, name, memberType = args[0], args[1], args[2]
	}
	if memberID == "" || name == "" || memberType == "" {
		err = fmt.Errorf("member ID, name, and type are required")
		return
	}
	if strings.HasSuffix(memberType, "-agent") {
		// In non-interactive mode (all three args provided), default to empty interface.
		if len(args) >= 3 {
			return
		}
		iface, err = promptMemberInterface()
		if err != nil {
			return
		}
	}
	return
}

// promptMemberInterface prompts for and validates member_interface JSON for agent members.
// An empty input defaults to an empty object {}.
func promptMemberInterface() (map[string]any, error) {
	for {
		raw, err := PromptOptional("Member interface JSON (optional): ")
		if err != nil {
			return nil, err
		}
		if raw == "" {
			return map[string]any{}, nil
		}
		var parsed map[string]any
		if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
			fmt.Printf("Invalid JSON: %v. Try again or press Enter to skip.\n", err)
			continue
		}
		return parsed, nil
	}
}
