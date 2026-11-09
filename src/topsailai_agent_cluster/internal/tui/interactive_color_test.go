package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// These tests cross the real REPL writer boundary. Every other colour test calls a
// renderer directly with an injected ColorPolicy and a plain builder, so it cannot
// observe that RunInteractive wraps stdout in a sanitizing writer. That blind spot
// let the endpoint table and the post-action tables lose their colour while the
// renderer tests stayed green.

// colouredScopeStub serves two endpoints with explicit connection states, so the
// connection-state colour mapping is actually exercised instead of falling through
// to the unknown-state default.
func colouredScopeStub() *interactiveStub {
	stub := scopeStub()
	stub.endpoints[0].ConnectionState = "online"
	stub.endpoints[1].ConnectionState = "offline"
	return stub
}

// TestInteractiveEndpointsKeepsColour proves the endpoint table keeps its styling
// through the REPL boundary. The table is trusted application styling over cells
// that escapeCell already sanitized, so the sanitizing writer must not strip it.
func TestInteractiveEndpointsKeepsColour(t *testing.T) {
	stub := colouredScopeStub()
	output, diagnostics := runScope(t, stub, "endpoints\nquit\n", ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, ansiBoldCyan+"ENDPOINT_ID") {
		t.Fatalf("endpoints table lost its styled header through the REPL: %q", output)
	}
	if !strings.Contains(output, ansiGreen+"endpoint-1") {
		t.Fatalf("endpoints table lost its online colour through the REPL: %q", output)
	}
	if !strings.Contains(output, ansiRed+"endpoint-2") {
		t.Fatalf("endpoints table lost its offline colour through the REPL: %q", output)
	}
}

// TestInteractiveEndpointsStaysPlainWithoutColour proves the same path emits no
// escape sequences when colour is disabled, so the fix never forces colour onto a
// redirected stream or a --no-color run.
func TestInteractiveEndpointsStaysPlainWithoutColour(t *testing.T) {
	stub := colouredScopeStub()
	output, diagnostics := runScope(t, stub, "endpoints\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "\x1b[") {
		t.Fatalf("plain endpoints table emitted escape sequences: %q", output)
	}
	if !strings.Contains(output, "ENDPOINT_ID") {
		t.Fatalf("plain endpoints table missing its header: %q", output)
	}
}

// TestInteractiveEndpointsSanitizesReportedValues proves routing the table to the
// trusted writer did not weaken sanitization: a hostile reported value must still
// be stripped, because the trusted writer keeps SGR sequences.
func TestInteractiveEndpointsSanitizesReportedValues(t *testing.T) {
	stub := colouredScopeStub()
	stub.endpoints[0].DisplayName = "evil\x1b[31mname"
	output, diagnostics := runScope(t, stub, "endpoints\nquit\n", ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "evil\x1b[31mname") {
		t.Fatalf("reported value reached the terminal unsanitized: %q", output)
	}
}

// TestInteractiveStartTableKeepsColour proves the post-start table keeps its
// styling. The receipt stays sanitized because it carries the provider's own
// document, while the table is trusted application styling.
func TestInteractiveStartTableKeepsColour(t *testing.T) {
	stub := newStartRefreshStub()
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("start receipt missing: %q", output)
	}
	if !strings.Contains(output, ansiBoldCyan+"NO") {
		t.Fatalf("post-start table lost its styled header through the REPL: %q", output)
	}
}

// TestInteractiveStartTableStaysPlainWithoutColour proves the post-start table
// emits no escape sequences when colour is disabled.
func TestInteractiveStartTableStaysPlainWithoutColour(t *testing.T) {
	stub := newStartRefreshStub()
	output, diagnostics := runScope(t, stub, startRefreshInput, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "\x1b[") {
		t.Fatalf("plain post-start table emitted escape sequences: %q", output)
	}
}

// TestInteractiveSendDegradedSnapshotKeepsProviderColour proves the degraded
// automatic step after a send keeps the provider's own colour. This scenario
// runs without a keypress seam, so the automatic step is the bounded snapshot
// substitute rather than a live tail; the snapshot body is provider text, and
// filterProviderOutput keeps SGR only when the policy is enabled, so the trusted
// writer is safe here and the operator sees the provider's styling.
func TestInteractiveSendDegradedSnapshotKeepsProviderColour(t *testing.T) {
	stub := newSendRefreshStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at_ms:") {
		t.Fatalf("automatic snapshot missing: %q", output)
	}
	if !strings.Contains(output, "log\x1b[31m") {
		t.Fatalf("automatic snapshot lost the provider's colour through the REPL: %q", output)
	}
}

// TestInteractiveSendDegradedSnapshotStaysPlainWithoutColour proves the degraded
// automatic step strips the provider's colour when colour is disabled, so a
// redirected stream never receives escape sequences.
func TestInteractiveSendDegradedSnapshotStaysPlainWithoutColour(t *testing.T) {
	stub := newSendRefreshStub()
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "\x1b[") {
		t.Fatalf("plain automatic snapshot emitted escape sequences: %q", output)
	}
}

// hostileOutputStub serves a snapshot body carrying a non-SGR control sequence, so a
// test can prove the trusted writer still strips terminal control that is not colour.
type hostileOutputStub struct {
	*sendRefreshStub
}

func (s *hostileOutputStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{Data: "before\x1b[2Jafter"}, nil
}

// TestInteractiveSendDegradedSnapshotStripsNonSGRControl proves the degraded
// automatic step's snapshot body is still stripped of terminal control sequences
// even though it is written through the trusted writer. Keeping SGR is the only
// exception, so a cursor-clear sequence must never reach the terminal.
func TestInteractiveSendDegradedSnapshotStripsNonSGRControl(t *testing.T) {
	stub := &hostileOutputStub{sendRefreshStub: newSendRefreshStub()}
	output, diagnostics := runScope(t, stub, sendScenario, ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "\x1b[2J") {
		t.Fatalf("non-SGR control sequence reached the terminal: %q", output)
	}
	if !strings.Contains(output, "beforeafter") {
		t.Fatalf("snapshot body was not preserved around the stripped sequence: %q", output)
	}
}

// TestOutputColorPolicyFollowsTheBoundary proves the colour decision belongs to the
// output boundary. A writer that reports a policy is honoured, and an unknown writer
// keeps colour disabled so it never receives escape sequences it did not ask for.
func TestOutputColorPolicyFollowsTheBoundary(t *testing.T) {
	enabled := ColorPolicy{Enabled: true}
	if got := OutputColorPolicy(colorPolicyWriter{policy: enabled}); got != enabled {
		t.Fatalf("boundary policy=%+v want %+v", got, enabled)
	}
	if got := OutputColorPolicy(&strings.Builder{}); got.Enabled {
		t.Fatalf("unknown boundary enabled colour: %+v", got)
	}
}

// colorPolicyWriter is a minimal boundary that reports a colour policy.
type colorPolicyWriter struct {
	policy ColorPolicy
}

func (w colorPolicyWriter) Write(p []byte) (int, error) { return len(p), nil }

func (w colorPolicyWriter) ColorPolicy() ColorPolicy { return w.policy }

// TestInteractiveListKeepsColour proves the list table, which already used the
// trusted writer, still keeps its styling, so the shared boundary is consistent.
func TestInteractiveListKeepsColour(t *testing.T) {
	stub := colouredScopeStub()
	output, diagnostics := runScope(t, stub, "list\nquit\n", ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, ansiBoldCyan+"NO") {
		t.Fatalf("list table lost its styled header through the REPL: %q", output)
	}
}

// TestInteractiveListStateColumnFollowsColour proves the state column is omitted only
// when colour actually carries the state. Dropping it while the writer strips colour
// would lose the information twice, which is the defect this fix removes.
func TestInteractiveListStateColumnFollowsColour(t *testing.T) {
	stub := colouredScopeStub()
	coloured, diagnostics := runScope(t, stub, "list\nquit\n", ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(coloured, "SESSION_STATUS") {
		t.Fatalf("coloured list kept the redundant state column: %q", coloured)
	}
	plain, diagnostics := runScope(t, stub, "list\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(plain, "SESSION_STATUS") {
		t.Fatalf("plain list dropped the state column: %q", plain)
	}
}
