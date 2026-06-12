// Package main provides interactive prompt utilities using readline for the ACS CLI terminal.
package main

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/chzyer/readline"
)

// ErrCancelled is returned when the user cancels an interactive prompt.
var ErrCancelled = fmt.Errorf("cancelled")

// InteractivePrompt wraps readline for step-by-step parameter collection.
type InteractivePrompt struct {
	rl *readline.Instance
}

// NewInteractivePrompt creates a new interactive prompt with the given prompt string.
func NewInteractivePrompt(prompt string) (*InteractivePrompt, error) {
	rl, err := readline.New(prompt)
	if err != nil {
		return nil, fmt.Errorf("failed to create readline: %w", err)
	}
	return &InteractivePrompt{rl: rl}, nil
}

// Close closes the readline instance.
func (p *InteractivePrompt) Close() error {
	if p.rl != nil {
		return p.rl.Close()
	}
	return nil
}

// PromptString prompts for a string value. Returns ErrCancelled if input is empty.
func (p *InteractivePrompt) PromptString(label string, required bool) (string, error) {
	for {
		p.rl.SetPrompt(label + ": ")
		line, err := p.rl.Readline()
		if err != nil {
			return "", ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			if !required {
				return "", nil
			}
			printWarning("This field is required. Press Ctrl+C to cancel.")
			continue
		}
		return line, nil
	}
}

// PromptStringWithDefault prompts for a string with a default value.
func (p *InteractivePrompt) PromptStringWithDefault(label, defaultValue string) (string, error) {
	p.rl.SetPrompt(fmt.Sprintf("%s [%s]: ", label, defaultValue))
	line, err := p.rl.Readline()
	if err != nil {
		return "", ErrCancelled
	}
	line = strings.TrimSpace(line)
	if line == "" {
		return defaultValue, nil
	}
	return line, nil
}

// PromptInt prompts for an integer value.
func (p *InteractivePrompt) PromptInt(label string, required bool) (int, error) {
	for {
		p.rl.SetPrompt(label + ": ")
		line, err := p.rl.Readline()
		if err != nil {
			return 0, ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			if !required {
				return 0, nil
			}
			printWarning("This field is required. Press Ctrl+C to cancel.")
			continue
		}
		val, err := strconv.Atoi(line)
		if err != nil {
			printWarning("Please enter a valid integer.")
			continue
		}
		return val, nil
	}
}

// PromptBool prompts for a boolean value (y/n).
func (p *InteractivePrompt) PromptBool(label string, defaultValue bool) (bool, error) {
	defaultStr := "n"
	if defaultValue {
		defaultStr = "y"
	}
	p.rl.SetPrompt(fmt.Sprintf("%s [y/N] [%s]: ", label, defaultStr))
	line, err := p.rl.Readline()
	if err != nil {
		return false, ErrCancelled
	}
	line = strings.ToLower(strings.TrimSpace(line))
	if line == "" {
		return defaultValue, nil
	}
	return line == "y" || line == "yes", nil
}

// PromptChoice prompts the user to choose from a list of options.
func (p *InteractivePrompt) PromptChoice(label string, options []string) (int, string, error) {
	fmt.Println(label + ":")
	for i, opt := range options {
		fmt.Printf("  %d) %s\n", i+1, opt)
	}
	for {
		p.rl.SetPrompt("Select (number): ")
		line, err := p.rl.Readline()
		if err != nil {
			return -1, "", ErrCancelled
		}
		line = strings.TrimSpace(line)
		if line == "" {
			printWarning("Please select an option. Press Ctrl+C to cancel.")
			continue
		}
		idx, err := strconv.Atoi(line)
		if err != nil || idx < 1 || idx > len(options) {
			printWarning("Invalid selection. Please enter a valid number.")
			continue
		}
		return idx - 1, options[idx-1], nil
	}
}

// PromptPassword prompts for a password (hidden input).
func (p *InteractivePrompt) PromptPassword(label string) (string, error) {
	p.rl.SetPrompt(label + ": ")
	// Note: readline does not natively support hidden input.
	// We use standard readline here; for production, consider term.ReadPassword.
	line, err := p.rl.Readline()
	if err != nil {
		return "", ErrCancelled
	}
	return strings.TrimSpace(line), nil
}

// --- Predefined interactive flows ---

// PromptGroupCreate prompts for group creation parameters.
func PromptGroupCreate(p *InteractivePrompt) (name, context, key string, err error) {
	printInfo("Creating a new group. Press Ctrl+C or Enter without input to cancel.")
	name, err = p.PromptString("Group name", true)
	if err != nil {
		return "", "", "", err
	}
	context, err = p.PromptString("Group context (description)", false)
	if err != nil {
		return "", "", "", err
	}
	key, err = p.PromptPassword("Group key (leave empty for public)")
	if err != nil {
		return "", "", "", err
	}
	return name, context, key, nil
}

// PromptGroupUpdate prompts for group update parameters.
func PromptGroupUpdate(p *InteractivePrompt) (name, context, key string, err error) {
	printInfo("Updating group. Press Ctrl+C or Enter without input to cancel.")
	name, err = p.PromptString("New group name (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	context, err = p.PromptString("New group context (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	key, err = p.PromptPassword("New group key (leave empty to keep current)")
	if err != nil {
		return "", "", "", err
	}
	return name, context, key, nil
}

// PromptMemberAdd prompts for member addition parameters.
func PromptMemberAdd(p *InteractivePrompt) (memberID, memberName, memberDesc, memberType string, memberInterface map[string]interface{}, err error) {
	printInfo("Adding a member. Press Ctrl+C or Enter without input to cancel.")
	memberID, err = p.PromptString("Member ID", true)
	if err != nil {
		return "", "", "", "", nil, err
	}
	memberName, err = p.PromptString("Member name", true)
	if err != nil {
		return "", "", "", "", nil, err
	}
	memberDesc, err = p.PromptString("Member description", false)
	if err != nil {
		return "", "", "", "", nil, err
	}
	_, memberType, err = p.PromptChoice("Member type", []string{"user", "manager-agent", "worker-agent"})
	if err != nil {
		return "", "", "", "", nil, err
	}
	// Member interface is optional JSON; skip for simplicity in CLI.
	return memberID, memberName, memberDesc, memberType, nil, nil
}

// PromptMemberUpdate prompts for member update parameters.
func PromptMemberUpdate(p *InteractivePrompt) (memberName, memberDesc, memberStatus string, err error) {
	printInfo("Updating member. Press Ctrl+C or Enter without input to cancel.")
	memberName, err = p.PromptString("New member name (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	memberDesc, err = p.PromptString("New member description (leave empty to keep current)", false)
	if err != nil {
		return "", "", "", err
	}
	_, memberStatus, err = p.PromptChoice("New member status", []string{"online", "offline", "idle", "processing"})
	if err != nil {
		return "", "", "", err
	}
	return memberName, memberDesc, memberStatus, nil
}

// PromptMessageEdit prompts for message edit parameters.
func PromptMessageEdit(p *InteractivePrompt) (text string, err error) {
	printInfo("Editing message. Press Ctrl+C or Enter without input to cancel.")
	text, err = p.PromptString("New message text", true)
	if err != nil {
		return "", err
	}
	return text, nil
}
