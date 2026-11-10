package tui

import (
	"strings"
	"testing"
)

// startHelpAutoFollowParameters are the two parameter lines that describe the
// automatic tail armed after a completed start. They are asserted as literal text
// here on purpose: the batch2 transcript fixture derives its parameter block from
// commandHelpCatalog, so without this test nothing would pin what the operator
// actually reads, and a catalog edit could silently change the documented
// behaviour while every derived assertion stayed green.
var startHelpAutoFollowParameters = []string{
	"after a completed start: force one collection for the selected endpoint, then start the same live tail as logs -f for the session that appeared, so the new session is watched without typing logf; the tail is armed after the collection because the launched session generation is minted by it, and any key stops it",
	"no tail is armed when no session appeared yet, when more than one appeared, when the generation is unverified, or when the client cannot stream; the reason is reported as a diagnostic, and a client that cannot stop a tail renders one bounded snapshot instead",
}

// TestStartHelpPinsAutoFollowParameters pins the rendered start help body, so the
// documented auto-follow behaviour cannot drift away from the catalog unnoticed.
func TestStartHelpPinsAutoFollowParameters(t *testing.T) {
	var out strings.Builder
	if err := PrintScopedCommandHelp(&out, "start", ScopeWorkspace); err != nil {
		t.Fatalf("PrintScopedCommandHelp: %v", err)
	}
	rendered := out.String()
	lines := strings.Split(rendered, "\n")

	for _, parameter := range startHelpAutoFollowParameters {
		want := "  " + parameter
		if !containsExactLine(lines, want) {
			t.Fatalf("start help is missing the auto-follow parameter line %q\nrendered:\n%s", want, rendered)
		}
	}

	// Position matters: both lines belong to the parameter block, so they must sit
	// after the empty-task rejection and before the --json rejection. A line that
	// moved into the description or the examples would still be present but would
	// no longer be a parameter, and the operator would read a different structure.
	emptyTask := lineIndex(lines, "  an empty multi-line task is rejected instead of submitting nothing")
	jsonRejected := lineIndex(lines, "  --json: rejected in interactive mode")
	if emptyTask < 0 || jsonRejected < 0 {
		t.Fatalf("start help lost its parameter block anchors: emptyTask=%d jsonRejected=%d\nrendered:\n%s", emptyTask, jsonRejected, rendered)
	}
	for _, parameter := range startHelpAutoFollowParameters {
		index := lineIndex(lines, "  "+parameter)
		if index < emptyTask || index > jsonRejected {
			t.Fatalf("auto-follow parameter at line %d is outside the parameter block (%d..%d)\nrendered:\n%s", index, emptyTask, jsonRejected, rendered)
		}
	}

	// The tail is armed after the collection, not before it, because the launched
	// session generation is minted by that collection. Asserting the order keeps a
	// future rewrite from reversing two steps that cannot be reversed in practice.
	armed := lineIndex(lines, "  "+startHelpAutoFollowParameters[0])
	skipped := lineIndex(lines, "  "+startHelpAutoFollowParameters[1])
	if armed < 0 || skipped < 0 || armed > skipped {
		t.Fatalf("auto-follow parameters are out of order: armed=%d skipped=%d", armed, skipped)
	}
}

// TestStartHelpAutoFollowParametersAreCatalogParameters verifies that the pinned
// lines really are catalog parameters, so this test cannot pass by matching text
// that the renderer emitted from somewhere else.
func TestStartHelpAutoFollowParametersAreCatalogParameters(t *testing.T) {
	entry := commandHelpCatalog["start"]
	for _, parameter := range startHelpAutoFollowParameters {
		found := false
		for _, candidate := range entry.parameters {
			if candidate == parameter {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("catalog start parameters do not contain %q", parameter)
		}
	}
}

// containsExactLine reports whether lines holds want as a whole line.
func containsExactLine(lines []string, want string) bool {
	return lineIndex(lines, want) >= 0
}

// lineIndex returns the index of the first line equal to want, or -1.
func lineIndex(lines []string, want string) int {
	for index, line := range lines {
		if line == want {
			return index
		}
	}
	return -1
}
