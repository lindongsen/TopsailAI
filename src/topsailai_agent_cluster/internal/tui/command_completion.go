package tui

import (
	"fmt"
	"strings"
	"unicode"
)

// completeCommand completes only the command token at a named scope prompt.
func (t *TerminalEditor) completeCommand(prompt string) error {
	prompt = strings.TrimPrefix(prompt, ansiBoldGreen)
	var kind ScopeKind
	switch {
	case strings.HasPrefix(prompt, "workspace>"):
		kind = ScopeWorkspace
	case strings.HasPrefix(prompt, "endpoint["):
		kind = ScopeEndpoint
	case strings.HasPrefix(prompt, "session["):
		kind = ScopeSession
	default:
		return nil
	}
	e := t.editor
	if e.overflow || e.cursor != len(e.text) || strings.IndexFunc(string(e.text), unicode.IsSpace) >= 0 {
		return nil
	}
	prefix := string(e.text)
	// The command prefix is a form, so completion matches the bare command word
	// while the typed prefix stays in the buffer; the inserted suffix therefore
	// appends to it instead of replacing it.
	matchPrefix := trimCommandPrefix(prefix)
	if matchPrefix == "/" {
		matchPrefix = ""
	}
	matches := []string{}
	for _, name := range availableCommands(kind) {
		if strings.HasPrefix(name, matchPrefix) {
			matches = append(matches, name)
		}
	}
	if len(matches) == 0 {
		return nil
	}
	common := matches[0]
	for _, name := range matches[1:] {
		for !strings.HasPrefix(name, common) {
			common = common[:len(common)-1]
		}
	}
	suffix := strings.TrimPrefix(common, matchPrefix)
	if len(matches) == 1 {
		suffix += " "
	}
	// Completion must not poison an otherwise valid line when it cannot fit.
	if e.bytes+len(suffix) <= e.limit {
		for _, r := range suffix {
			e.insert(r)
		}
	}
	if len(matches) > 1 {
		// The candidate list replaces the input block instead of being printed
		// inside it, so the next redraw starts below the list and never erases
		// it. Erasing first also keeps the cursor out of the middle of a
		// multi-row block.
		if err := t.eraseBlock(); err != nil {
			return err
		}
		_, err := fmt.Fprintf(t.output, "%s\r\n", strings.Join(matches, "  "))
		return err
	}
	return nil
}
