package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestTerminalTabCompletesCtlActions proves dotted completion offers the
// Endpoint's advertised actions rather than the command words.
func TestTerminalTabCompletesCtlActions(t *testing.T) {
	actions := []string{"agent.tokens", "git.branch", "git.diff", "git.status", "session.messages"}
	for _, c := range []struct {
		name, input, want, candidates string
		limit                         int
	}{
		// A unique prefix completes the whole action and appends a space, so the
		// operator can type a parameter immediately.
		{"unique", "ctl.git.st\t\r", "ctl.git.status ", "", 128},
		// An ambiguous prefix completes only the common part and lists the
		// candidates, so the operator chooses instead of guessing.
		{"ambiguous", "ctl.git.\t\r", "ctl.git.", "ctl.git.branch  ctl.git.diff  ctl.git.status", 128},
		// An empty action lists every advertised action, which is how the
		// shortcuts are discovered without the numbered menu.
		{"all", "ctl.\t\r", "ctl.", "ctl.agent.tokens", 128},
		// An unadvertised action leaves the buffer untouched, so completion never
		// invents an action the Endpoint would refuse.
		{"unknown", "ctl.nope\t\r", "ctl.nope", "", 128},
		// A line that already carries a parameter is not completed, because
		// parameters are not completed and rewriting the word would move the
		// operator's cursor away from the argument.
		{"parameter", "ctl.git.status reason=x\t\r", "ctl.git.status reason=x", "", 128},
		// A command word that is not the dotted spelling keeps the previous
		// behaviour, so an argument is never rewritten.
		{"command", "send {}\t\r", "send {}", "", 128},
		// A bounded line keeps the previous behaviour when the suffix cannot fit.
		{"bounded", "ctl.git.st\t\r", "ctl.git.st", "", 12},
	} {
		t.Run(c.name, func(t *testing.T) {
			var out strings.Builder
			editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader(c.input)}, &out, func() int { return 80 }, func() (func() error, error) {
				return func() error { return nil }, nil
			})
			editor.SetActionSource(func() []string { return actions })
			got, bad, err := editor.ReadLine(context.Background(), "session[demo/id]> ", true, c.limit)
			if err != nil || bad || got != c.want {
				t.Fatalf("got=%q overflow=%v err=%v", got, bad, err)
			}
			if c.candidates != "" && !strings.Contains(out.String(), c.candidates) {
				t.Fatalf("missing candidates %q in %q", c.candidates, out.String())
			}
		})
	}
}

// TestTerminalTabWithoutActionSource proves an editor without a capability seam
// keeps the previous behaviour instead of completing an action it cannot know.
func TestTerminalTabWithoutActionSource(t *testing.T) {
	var out strings.Builder
	editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("ctl.git.st\t\r")}, &out, func() int { return 80 }, func() (func() error, error) {
		return func() error { return nil }, nil
	})
	got, bad, err := editor.ReadLine(context.Background(), "session[demo/id]> ", true, 128)
	if err != nil || bad || got != "ctl.git.st" {
		t.Fatalf("got=%q overflow=%v err=%v", got, bad, err)
	}
}

// TestCtlActionCacheQueriesOncePerEndpoint proves completion never performs a
// capability query per keystroke: the cache refreshes on a scope change only.
func TestCtlActionCacheQueriesOncePerEndpoint(t *testing.T) {
	stub := ctlStub(
		protocol.Capability{Name: "ctl.git.status", Version: "v1"},
		protocol.Capability{Name: "ctl.session.messages", Version: "v1"},
		protocol.Capability{Name: "message.send", Version: "v1"},
	)
	cache := NewCtlActionCache()
	for range 5 {
		cache.Actions(context.Background(), stub, "endpoint-1")
	}
	if got, want := strings.Join(cache.Cached(), ","), "git.status,session.messages"; got != want {
		t.Fatalf("cached=%s want=%s", got, want)
	}
	// A different Endpoint refreshes the list, so a scope change is observed.
	stub.capabilities = []protocol.Capability{{Name: "ctl.agent.tokens", Version: "v1"}}
	cache.Actions(context.Background(), stub, "endpoint-2")
	if got, want := strings.Join(cache.Cached(), ","), "agent.tokens"; got != want {
		t.Fatalf("cached=%s want=%s", got, want)
	}
}

// TestCtlActionCacheFailureCompletesNothing proves a failed capability query
// leaves completion empty instead of offering an action the Endpoint may not
// support, and that the failure is not retried on every prompt.
func TestCtlActionCacheFailureCompletesNothing(t *testing.T) {
	cache := NewCtlActionCache()
	cache.Actions(context.Background(), nil, "endpoint-1")
	if got := cache.Cached(); len(got) != 0 {
		t.Fatalf("cached=%v want empty", got)
	}
}
