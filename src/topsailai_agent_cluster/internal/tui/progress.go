package tui

import (
	"io"
	"strings"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// progressThreshold is how long a command may run before its progress block is
// printed. A command that finishes sooner prints nothing at all, because a hint
// that appears and disappears within one frame is noise rather than information.
// The fast read commands answer in milliseconds, so they stay silent.
const progressThreshold = 200 * time.Millisecond

// progressStageIndent prefixes every stage row, so the stage list reads as a
// subordinate block under the header instead of as more output.
const progressStageIndent = "  "

// ProgressBoundary reports whether an output boundary can render progress lines.
// A writer that does not report one keeps progress disabled, so an unknown
// boundary never receives progress it did not ask for. It mirrors
// ColorPolicyProvider: the boundary owns the presentation decision, and a
// renderer never probes global terminal state.
type ProgressBoundary interface {
	ProgressEligible() bool
}

// progressEligible reports whether out asked for progress lines.
func progressEligible(out io.Writer) bool {
	boundary, ok := out.(ProgressBoundary)
	return ok && boundary.ProgressEligible()
}

// ActionProgress reports the real lifecycle stages of one command while the
// client waits for its durable result.
//
// It reports observed stages only: every stage row comes from a durable command
// state the client already polled, so a progress row never claims more than the
// receipt will. It never animates, for two reasons. The REPL diagnostics writer
// strips carriage returns and cursor control, so an in-place animation would be
// printed as replacement runes; and a spinner unrelated to real progress would be
// a fabricated signal, which this project does not accept anywhere else.
//
// A nil *ActionProgress is valid and reports nothing, so a caller disables
// progress by passing nil instead of branching at every call site.
type ActionProgress struct {
	mu        sync.Mutex
	out       io.Writer
	policy    ColorPolicy
	header    string
	threshold time.Duration
	start     time.Time
	now       func() time.Time
	pending   []string
	// last is the most recently accepted stage, kept across flushes. The pending
	// buffer is cleared on every flush, so comparing against it alone would let the
	// wait loop reprint an unchanged state on every poll.
	last    string
	emitted bool
}

// NewActionProgress builds the progress reporter for one action, or returns nil
// when the boundary cannot render progress. The caller passes the writer it
// already owns, so no new parameter is threaded through the command surface.
//
// Both the eligibility and the colour policy come from that writer, so a
// redirected diagnostics stream stays plain and a terminal one is styled, without
// this reporter probing global terminal state.
func NewActionProgress(out io.Writer, request ActionRequest) *ActionProgress {
	return NewProgress(out, progressHeader(request))
}

// NewProgress builds the progress reporter for one described operation, or
// returns nil when the boundary cannot render progress or the header is empty.
// It exists for operations that are not commands, such as a forced collection,
// which has no ActionRequest but still leaves the operator waiting.
func NewProgress(out io.Writer, header string) *ActionProgress {
	if out == nil || header == "" || !progressEligible(out) {
		return nil
	}
	return &ActionProgress{
		out:       out,
		policy:    OutputColorPolicy(out),
		header:    header,
		threshold: progressThreshold,
		start:     time.Now(),
		now:       time.Now,
	}
}

// Stage records one observed lifecycle stage. The stage is buffered until the
// threshold passes, so a fast command prints nothing at all. A repeated stage is
// not a new fact, so it is never printed twice.
func (p *ActionProgress) Stage(stage string) {
	if p == nil || stage == "" {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.last == stage {
		return
	}
	p.last = stage
	p.pending = append(p.pending, stage)
	p.flushLocked()
}

// Tick gives the reporter a chance to print buffered stages once the threshold
// has passed. The wait loop calls it on every poll, so a command whose state does
// not change still shows its progress block instead of staying silent.
func (p *ActionProgress) Tick() {
	if p == nil {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	p.flushLocked()
}

// flushLocked writes the header and every buffered stage once the threshold has
// passed. The caller holds the lock, because a concurrent collector may report a
// stage from another goroutine.
//
// A write failure is deliberately ignored: progress is best-effort presentation,
// so a closed or broken diagnostics stream must never change the outcome of the
// command it is describing.
func (p *ActionProgress) flushLocked() {
	if len(p.pending) == 0 {
		return
	}
	if p.now().Sub(p.start) < p.threshold {
		return
	}
	if !p.emitted {
		p.emitted = true
		_, _ = io.WriteString(p.out, p.header+"\n")
	}
	for _, stage := range p.pending {
		_ = writeStyled(p.out, ansiDim, progressStageIndent+stage, p.policy)
		_, _ = io.WriteString(p.out, "\n")
	}
	p.pending = p.pending[:0]
}

// progressHeader builds the one-line description of the action in flight, or an
// empty string for an operation this reporter does not describe.
func progressHeader(request ActionRequest) string {
	verb := progressVerb(request.Operation)
	if verb == "" {
		return ""
	}
	target := progressTarget(request)
	if target == "" {
		return verb + "..."
	}
	return verb + " " + target + "..."
}

// progressVerb maps a standard operation onto the operator-facing verb. Only
// standard operations are described, so a provider-specific action can never
// acquire a wording of its own here.
func progressVerb(operation string) string {
	switch operation {
	case protocol.OperationMessageSend:
		return "sending message to"
	case protocol.OperationContextInject:
		return "injecting context into"
	case protocol.OperationExecutionInterrupt:
		return "interrupting"
	case protocol.OperationAgentStart:
		return "starting agent"
	case protocol.OperationAgentResume:
		return "resuming agent"
	case protocol.OperationAgentStop:
		return "stopping agent"
	case protocol.OperationAgentDriveStart:
		return "starting drive controller for"
	case protocol.OperationAgentDriveStop:
		return "stopping drive controller for"
	case protocol.OperationCommandExec:
		return "executing command in"
	}
	if strings.HasPrefix(operation, ctlOperationPrefix) {
		return "running control " + strings.TrimPrefix(operation, ctlOperationPrefix) + " on"
	}
	return ""
}

// progressTarget names the exact target of the action. Every interpolated value
// is sanitized first, because a provider identifier is untrusted text and this
// line is written with trusted styling.
//
// The reported session name is named first, matching the confirmation question, so
// the operator reads the same target description before and after answering. It
// never replaces an identifier: the opaque resource ID stays, because it is what
// `status` accepts.
func progressTarget(request ActionRequest) string {
	endpoint := sanitizeInlineText(request.EndpointID)
	session := sanitizeInlineText(request.ResourceID)
	name := sanitizeInlineText(request.DisplayName)
	// A start targets a launch profile rather than a session, so naming a session
	// there would describe a target the action does not have.
	if request.Operation == protocol.OperationAgentStart {
		profile := sanitizeInlineText(request.Profile)
		switch {
		case profile == "" && endpoint == "":
			return ""
		case profile == "":
			return "on endpoint " + endpoint
		case endpoint == "":
			return "from profile " + profile
		}
		return "from profile " + profile + " on endpoint " + endpoint
	}
	if session == "" && endpoint == "" {
		return ""
	}
	described := session
	if name != "" {
		described = `"` + name + `"`
		if session != "" {
			described += " " + session
		}
	}
	switch {
	case described == "":
		return "endpoint " + endpoint
	case endpoint == "":
		return "session " + described
	}
	return "session " + described + " (" + endpoint + ")"
}
