package endpoint

import (
	"bufio"
	"bytes"
	"fmt"
	"strings"
	"sync"
)

// allowEmptyDirective is the explicit marker a file must contain before an empty
// allowlist is accepted. Without it an empty file is rejected, so a truncated or
// accidentally emptied file cannot silently disable every command.
const allowEmptyDirective = "allow-empty"

// commandExecutingPrograms lists programs that can run another command. A single
// token entry for one of these would authorize the whole program, including its
// ability to execute arbitrary commands, so such an entry is rejected at load
// time. For example a bare "git" entry would permit "git -c core.fsmonitor=...".
var commandExecutingPrograms = map[string]struct{}{
	"awk": {}, "bash": {}, "docker": {}, "env": {}, "find": {}, "git": {},
	"kubectl": {}, "make": {}, "node": {}, "perl": {}, "python": {}, "python3": {},
	"ruby": {}, "sed": {}, "sh": {}, "xargs": {},
}

// Allowlist is an Endpoint-global command allowlist. Entries are token sequences
// matched by prefix against an argv array, so an entry "git status" permits
// "git status --short" and rejects "git -c core.fsmonitor=...".
//
// The list is safe for concurrent use and can be replaced atomically, which is
// what makes reload possible without restarting the Endpoint.
type Allowlist struct {
	mu      sync.RWMutex
	entries [][]string
}

// ParseAllowlist parses a line-based allowlist document. Each non-empty line that
// does not start with '#' is one entry, split on whitespace. A line containing
// only the allow-empty directive marks an intentionally empty list.
func ParseAllowlist(data []byte) ([][]string, error) {
	entries := make([][]string, 0)
	allowEmpty := false
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if line == allowEmptyDirective {
			allowEmpty = true
			continue
		}
		tokens := strings.Fields(line)
		if err := validateEntry(tokens); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNumber, err)
		}
		entries = append(entries, tokens)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read allowlist: %w", err)
	}
	if len(entries) == 0 && !allowEmpty {
		return nil, fmt.Errorf("allowlist is empty; add entries or the %q directive to disable every command intentionally", allowEmptyDirective)
	}
	return entries, nil
}

// validateEntry rejects an entry that would authorize a whole command-executing
// program, because prefix matching on a single token grants every subcommand.
func validateEntry(tokens []string) error {
	if len(tokens) == 0 {
		return fmt.Errorf("empty entry")
	}
	if len(tokens) == 1 {
		if _, risky := commandExecutingPrograms[tokens[0]]; risky {
			return fmt.Errorf("entry %q must name a subcommand, because %q can execute other commands", tokens[0], tokens[0])
		}
	}
	for _, token := range tokens {
		if strings.ContainsAny(token, "\x00\n\r") {
			return fmt.Errorf("entry contains a control character")
		}
	}
	return nil
}

// NewAllowlist builds an allowlist from already validated entries.
func NewAllowlist(entries [][]string) *Allowlist {
	copied := make([][]string, len(entries))
	for i, entry := range entries {
		copied[i] = append([]string(nil), entry...)
	}
	return &Allowlist{entries: copied}
}

// LoadAllowlist parses a document and returns the resulting allowlist.
func LoadAllowlist(data []byte) (*Allowlist, error) {
	entries, err := ParseAllowlist(data)
	if err != nil {
		return nil, err
	}
	return NewAllowlist(entries), nil
}

// Reload replaces the entries atomically. The new document is parsed completely
// before the swap, so a parse failure keeps the previous list in force and never
// leaves a partially applied or empty list behind.
func (a *Allowlist) Reload(data []byte) error {
	entries, err := ParseAllowlist(data)
	if err != nil {
		return err
	}
	a.mu.Lock()
	a.entries = entries
	a.mu.Unlock()
	return nil
}

// Len reports the number of entries currently in force.
func (a *Allowlist) Len() int {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return len(a.entries)
}

// Permit reports whether the argv array matches an allowlist entry by prefix.
// An empty allowlist permits nothing, so a missing policy fails closed.
func (a *Allowlist) Permit(argv []string) error {
	if len(argv) == 0 {
		return fmt.Errorf("empty command")
	}
	a.mu.RLock()
	defer a.mu.RUnlock()
	for _, entry := range a.entries {
		if hasPrefix(argv, entry) {
			return nil
		}
	}
	return fmt.Errorf("command %q is not allowed", strings.Join(argv, " "))
}

// hasPrefix reports whether argv starts with every token of the entry.
func hasPrefix(argv, entry []string) bool {
	if len(entry) == 0 || len(argv) < len(entry) {
		return false
	}
	for i, token := range entry {
		if argv[i] != token {
			return false
		}
	}
	return true
}
