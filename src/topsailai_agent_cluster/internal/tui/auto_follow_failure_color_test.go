package tui

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

type receiptSendFollowStub struct {
	*sendFollowStub
	result map[string]any
}

func (s *receiptSendFollowStub) GetCommand(context.Context, string) (map[string]any, error) {
	return s.result, nil
}
func TestUnitAutoFollowSkipsOnlyProvablyUnappliedResults(t *testing.T) {
	cases := []struct {
		name       string
		status     protocol.CommandStatus
		effect     protocol.EffectCertainty
		wantAction int
	}{
		{name: "rejected not applied", status: protocol.StatusRejected, effect: protocol.EffectNotApplied, wantAction: 0},
		{name: "unconfirmed unknown", status: protocol.StatusUnconfirmed, effect: protocol.EffectUnknown, wantAction: 1},
	}
	for _, tc := range cases {
		t.Run(tc.name+" send", func(t *testing.T) {
			base := newSendFollowStub()
			stub := &receiptSendFollowStub{sendFollowStub: base, result: map[string]any{"status": string(tc.status), "effect_certainty": string(tc.effect)}}
			_, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `send {"text":"hi"}`, "quit"})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if got := len(actionFollowRequests(base)); got != tc.wantAction {
				t.Fatalf("action follow count=%d, want %d", got, tc.wantAction)
			}
		})
		t.Run(tc.name+" btw", func(t *testing.T) {
			base := newSendFollowStub()
			stub := &receiptSendFollowStub{sendFollowStub: base, result: map[string]any{"status": string(tc.status), "effect_certainty": string(tc.effect)}}
			_, diagnostics, _ := runSendREPL(t, stub, []string{"cd host-one/endpoint-1/res-1", `btw {"text":"hi"}`, "y", "quit"})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if got := len(actionFollowRequests(base)); got != tc.wantAction {
				t.Fatalf("action follow count=%d, want %d", got, tc.wantAction)
			}
		})
	}
}

func TestUnitWriteInteractiveErrorColorsOnlyErrorAndSanitizesCause(t *testing.T) {
	var plain, colored strings.Builder
	cause := fmt.Errorf("bad\x1b[31mprovider\x1b[0m")
	if err := writeInteractiveError(&plain, ColorPolicy{}, "send", cause); err != nil {
		t.Fatal(err)
	}
	if err := writeInteractiveError(&colored, ColorPolicy{Enabled: true}, "send", cause); err != nil {
		t.Fatal(err)
	}
	plainText := plain.String()
	colorText := colored.String()
	if !strings.HasPrefix(colorText, ansiRed+"error: badprovider"+ansiReset+"\n") {
		t.Fatalf("error line is not safely red: %q", colorText)
	}
	if strings.Contains(colorText, "\x1b[31mprovider") {
		t.Fatalf("untrusted cause escape survived: %q", colorText)
	}
	if !strings.Contains(colorText, "usage: send") || !strings.Contains(colorText, "next: Run help send") {
		t.Fatalf("guidance missing: %q", colorText)
	}
	if strings.Contains(plainText, ansiRed) || !strings.HasPrefix(plainText, "error: badprovider\n") {
		t.Fatalf("unexpected no-color output: %q", plainText)
	}
}
