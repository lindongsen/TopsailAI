package tui

import (
	"context"
	"strings"
	"testing"
)

// TestTerminalTabCompletion exercises decoder, completion and terminal restoration together.
func TestTerminalTabCompletion(t *testing.T) {
	for _, c := range []struct {
		name, prompt, input, want, candidates string
		history                               bool
		limit                                 int
	}{
		{"unique", "workspace> ", "he\t\r", "help ", "", true, 128},
		{"ambiguous", "session[demo/id]> ", "st\t\r", "st", "stop  status", true, 128},
		{"empty", "workspace> ", "\t\t\r", "", "list  endpoints  cd", true, 128},
		{"unknown", "workspace> ", "xyz\t\r", "xyz", "", true, 128},
		{"scope", "workspace> ", "res\t\r", "resume ", "", true, 128},
		{"session", ansiBoldGreen + "session[demo/id]>" + ansiReset + " ", "bt\t\r", "btw ", "", true, 128},
		{"endpoint", "endpoint[demo]> ", "lo\t\r", "logs ", "", true, 128},
		{"argument", "session[demo/id]> ", "send {}\t\r", "send {}", "", true, 128},
		{"middle", "workspace> ", "hep\x1b[D\t\r", "hep", "", true, 128},
		{"answer", "workspace> ", "he\t\r", "he", "", false, 128},
		{"question", "Name: ", "he\t\r", "he", "", true, 128},
		{"bounded", "workspace> ", "he\t\r", "he", "", true, 4},
	} {
		t.Run(c.name, func(t *testing.T) {
			var out strings.Builder
			restored := 0
			editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader(c.input)}, &out, func() int { return 80 }, func() (func() error, error) {
				return func() error { restored++; return nil }, nil
			})
			got, bad, err := editor.ReadLine(context.Background(), c.prompt, c.history, c.limit)
			if err != nil || bad || got != c.want || restored != 1 {
				t.Fatalf("got=%q overflow=%v err=%v restored=%d", got, bad, err, restored)
			}
			if c.candidates != "" && !strings.Contains(out.String(), c.candidates) {
				t.Fatalf("missing candidates %q in %q", c.candidates, out.String())
			}
		})
	}
}
