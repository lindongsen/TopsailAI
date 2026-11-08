package tui

import (
	"fmt"
	"strings"
	"unicode"
)

// completeCommand completes the command token at a named scope prompt.
//
// Two candidate sets exist. A dotted control word such as ctl.git.st is completed
// from the Endpoint's advertised actions, because the action lives inside the
// command word. Every other command is completed from the command words of the
// current scope, and only while the line still holds a single token, so an
// argument is never rewritten.
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
	if e.overflow || e.cursor != len(e.text) {
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
	var matches []string
	if strings.HasPrefix(matchPrefix, ctlOperationPrefix) {
		// The dotted spelling carries the action inside the command word, so the
		// action is completed from the advertised capabilities. A line that
		// already carries a parameter is left untouched, because parameters are
		// not completed.
		if strings.IndexFunc(prefix, unicode.IsSpace) >= 0 {
			return nil
		}
		matches = t.completeCtlActions(matchPrefix)
	} else {
		if strings.IndexFunc(prefix, unicode.IsSpace) >= 0 {
			return nil
		}
		for _, name := range availableCommands(kind) {
			if strings.HasPrefix(name, matchPrefix) {
				matches = append(matches, name)
			}
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

// completeCtlActions returns the advertised control actions matching a typed
// dotted command word.
//
// The candidate set is the Endpoint's advertised actions rather than the command
// words, so a shortcut is completed from the same descriptor the Endpoint uses to
// authorize it. An empty action lists every action, which is how an operator
// discovers the shortcuts without the numbered menu.
//
// The source reads a cache and never performs network I/O, because this runs
// inside the keystroke handler. A nil source completes nothing, so an editor
// without a capability seam keeps the previous behaviour.
func (t *TerminalEditor) completeCtlActions(matchPrefix string) []string {
	if t.actions == nil {
		return nil
	}
	typed := strings.TrimPrefix(matchPrefix, ctlOperationPrefix)
	matches := []string{}
	for _, name := range t.actions() {
		if strings.HasPrefix(name, typed) {
			matches = append(matches, ctlOperationPrefix+name)
		}
	}
	return matches
}
