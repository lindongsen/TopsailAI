package main

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// interactiveOnlyCommands names the canonical commands that deliberately have no
// standalone spelling, with the reason each one is exempt.
//
// This set is the whole point of the test below. Without it the test would demand
// a standalone spelling for a command that cannot have one, and the only way to
// satisfy it would be to invent a meaningless command. With it, adding a new
// interactive command forces a decision: either give it a standalone spelling, or
// record here why it cannot have one. A silent omission is the defect this test
// exists to prevent.
var interactiveOnlyCommands = map[string]string{
	"cd":   "navigates REPL scope, which exists only inside the interactive loop; a standalone invocation has no scope to change",
	"quit": "ends the REPL loop; a standalone invocation already ends when its command finishes",
	"exit": "ends the REPL loop; a standalone invocation already ends when its command finishes",
	"watch": "its ticks are list or refresh, both of which have standalone spellings, and --trigger is a foreground convenience in the operator's own client process rather than a reliability promise",
}

// TestEveryInteractiveCommandHasAStandalonePath enforces the non-interactive first
// rule in the direction the audit found broken.
//
// The existing forward test proves every advertised standalone command is
// dispatched. That is the opposite direction: it catches help that promises a
// command the binary rejects, but it cannot catch a capability that exists only in
// the REPL, because such a capability is simply absent from the standalone help and
// nothing compares the two surfaces. Three real gaps were found that way: the model
// registry and model set operations, resume by provider session handle, and
// endpoint-scope command.exec. Each was advertised in the capability set and
// reachable from the REPL, and each was unreachable from a script.
//
// The comparison is made against the interactive command matrix rather than against
// a hand-written list, so a command added to the matrix is checked immediately.
func TestEveryInteractiveCommandHasAStandalonePath(t *testing.T) {
	advertised := make(map[string]bool)
	for _, line := range tui.NonInteractiveCommandHelpLines() {
		name := standaloneCommandName(line)
		if name == "" {
			t.Fatalf("cannot derive a command name from %q", line)
		}
		advertised[name] = true
	}
	if len(advertised) == 0 {
		t.Fatal("no standalone commands advertised")
	}

	canonical := tui.CanonicalCommands()
	if len(canonical) == 0 {
		t.Fatal("no canonical interactive commands registered")
	}

	for _, name := range canonical {
		if advertised[name] {
			continue
		}
		if reason, exempt := interactiveOnlyCommands[name]; exempt {
			if strings.TrimSpace(reason) == "" {
				t.Fatalf("interactive-only command %q is exempt without a reason", name)
			}
			continue
		}
		t.Fatalf("interactive command %q has no standalone spelling and is not a recorded exception; either add a standalone path or record why it cannot have one in interactiveOnlyCommands", name)
	}
}

// TestInteractiveOnlyExceptionsStayReal proves the exception set cannot rot in
// either direction.
//
// An entry that names a command the matrix no longer contains is a stale exemption
// that would silently excuse a future command of the same name. An entry that names
// a command which does have a standalone spelling is a false exemption that hides
// the very comparison this test performs. Both are checked, because an exception
// list is only trustworthy while every entry is still true.
func TestInteractiveOnlyExceptionsStayReal(t *testing.T) {
	canonical := make(map[string]bool)
	for _, name := range tui.CanonicalCommands() {
		canonical[name] = true
	}
	advertised := make(map[string]bool)
	for _, line := range tui.NonInteractiveCommandHelpLines() {
		advertised[standaloneCommandName(line)] = true
	}

	for name := range interactiveOnlyCommands {
		if !canonical[name] {
			t.Fatalf("exception %q is not a canonical interactive command; remove the stale exemption", name)
		}
		if advertised[name] {
			t.Fatalf("exception %q has a standalone spelling, so it must not be exempt", name)
		}
	}
}
