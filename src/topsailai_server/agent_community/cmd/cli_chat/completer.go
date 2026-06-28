// Package main provides readline completion for the ACS chat CLI.
package main

import (
	"strings"
	"sync"

	"github.com/chzyer/readline"
)

// Completer provides tab completion for commands and member mentions.
type Completer struct {
	mu      sync.RWMutex
	members []Member
}

// NewCompleter creates a new completer.
func NewCompleter() *Completer {
	return &Completer{}
}

// SetMembers updates the member list used for mention completion.
func (c *Completer) SetMembers(members []Member) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.members = members
}

// Do implements readline.AutoCompleter.
func (c *Completer) Do(line []rune, pos int) ([][]rune, int) {
	prefix := string(line[:pos])
	if strings.HasPrefix(prefix, "@") {
		return c.completeMention(prefix)
	}
	return c.completeCommand(prefix)
}

func (c *Completer) completeMention(prefix string) ([][]rune, int) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	query := strings.ToLower(strings.TrimPrefix(prefix, "@"))
	var matches [][]rune
	for _, m := range c.members {
		if query == "" || strings.HasPrefix(strings.ToLower(m.MemberName), query) || strings.HasPrefix(strings.ToLower(m.MemberID), query) {
			matches = append(matches, []rune(m.MemberName))
		}
	}
	return matches, len(query) + 1
}

func (c *Completer) completeCommand(prefix string) ([][]rune, int) {
	commands := []string{
		"/group list",
		"/group create",
		"/group leave",
		"/chat ",
		"/member list",
		"/member add",
		"/help",
		"exit",
		"quit",
	}
	var matches [][]rune
	for _, cmd := range commands {
		if strings.HasPrefix(cmd, prefix) {
			matches = append(matches, []rune(cmd))
		}
	}
	return matches, len(prefix)
}

// Ensure Completer implements readline.AutoCompleter.
var _ readline.AutoCompleter = (*Completer)(nil)
