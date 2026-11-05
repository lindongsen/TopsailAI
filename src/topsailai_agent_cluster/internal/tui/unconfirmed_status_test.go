package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestUnconfirmedStatusNeverClaimsConfirmedResult proves the operator is never told that a command
// whose effect is unknown produced a confirmed result, even if a receipt claims a confirmed exit.
func TestUnconfirmedStatusNeverClaimsConfirmedResult(t *testing.T) {
	cases := []protocol.ExecutionReceipt{
		{},
		{DeliveryBoundary: protocol.DeliverySignalSent, ExitConfirmed: false, EffectCertainty: protocol.EffectUnknown},
		{DeliveryBoundary: protocol.DeliverySignalSent, ExitConfirmed: true, EffectCertainty: protocol.EffectAcknowledged},
	}
	for _, receipt := range cases {
		got := StatusLabel(protocol.StatusUnconfirmed, receipt)
		if got != "delivery unconfirmed, effect unknown" {
			t.Fatalf("StatusLabel(unconfirmed, %#v)=%q", receipt, got)
		}
		for _, forbidden := range []string{"confirmed result", "stopped", "applied"} {
			if strings.Contains(got, forbidden) {
				t.Fatalf("label %q must not claim %q", got, forbidden)
			}
		}
	}
}

// TestUnconfirmedIsTerminalButExecutingIsNot proves the wait loop stops on the converged state and
// keeps waiting while the command is still executing.
func TestUnconfirmedIsTerminalButExecutingIsNot(t *testing.T) {
	if !IsTerminalState(map[string]any{"status": string(protocol.StatusUnconfirmed)}) {
		t.Fatal("unconfirmed must be terminal, otherwise a converged command is polled forever")
	}
	if IsTerminalState(map[string]any{"status": string(protocol.StatusExecuting)}) {
		t.Fatal("executing must not be terminal")
	}
}
