package genericcli

import (
	"testing"

	"topsailai_agent_cluster/internal/providercli"
)

// TestReceiptFromOperationCarriesProviderWarnings proves the adapter forwards a
// Provider warning into the Cluster receipt.
//
// The warning is the only evidence that a hard interrupt dropped the operator's
// message, so an adapter that dropped it here would leave a command that ran with
// text silently discarded and nothing to explain it. The empty case is asserted in
// the same table because a mapping that always allocated a slice would pass a
// non-empty-only test while making every warning-free command carry a field it
// never had.
func TestReceiptFromOperationCarriesProviderWarnings(t *testing.T) {
	warning := "hard_interrupt carries no message, so the supplied message was not delivered"
	cases := []struct {
		name     string
		warnings []string
		want     int
	}{
		{name: "one warning", warnings: []string{warning}, want: 1},
		{name: "no warnings", warnings: nil, want: 0},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			receipt := receiptFromOperation(providercli.OperationResult{
				DeliveryBoundary: providercli.DeliverySubmitted,
				EffectCertainty:  providercli.EffectAcknowledged,
				ProviderOutcome:  "submitted",
				Warnings:         testCase.warnings,
			})
			if len(receipt.Warnings) != testCase.want {
				t.Fatalf("receipt warnings = %#v, want %d", receipt.Warnings, testCase.want)
			}
			if testCase.want == 1 && receipt.Warnings[0] != warning {
				t.Fatalf("receipt warning = %q, want %q", receipt.Warnings[0], warning)
			}
			// A warning never changes the phase or the effect certainty: the command
			// ran, so it must still be reported as having run.
			if receipt.EffectCertainty != providercli.EffectAcknowledged {
				t.Fatalf("receipt effect certainty = %q, want acknowledged", receipt.EffectCertainty)
			}
		})
	}
}
