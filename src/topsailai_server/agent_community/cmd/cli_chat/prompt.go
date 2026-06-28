// Package main provides prompt management for the ACS chat CLI.
package main

import "sync"

// PromptManager builds the PS1 prompt string.
type PromptManager struct {
	mu       sync.RWMutex
	userName string
	groupID  string
}

// NewPromptManager creates a new PromptManager.
func NewPromptManager(userName string) *PromptManager {
	return &PromptManager{userName: userName}
}

// SetUser updates the user name.
func (p *PromptManager) SetUser(userName string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.userName = userName
}

// SetGroup sets the current group ID.
func (p *PromptManager) SetGroup(groupID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.groupID = groupID
}

// ClearGroup clears the current group ID.
func (p *PromptManager) ClearGroup() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.groupID = ""
}

// Prompt returns the prompt string.
func (p *PromptManager) Prompt() string {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if p.groupID != "" {
		return yellow("acs@" + p.userName + ":" + p.groupID + "# ")
	}
	return yellow("acs@" + p.userName + ": ")
}

// String returns the prompt string (alias for Prompt).
func (p *PromptManager) String() string {
	return p.Prompt()
}
