package tui

import (
	"context"
	"strings"
	"testing"
)

// TestRefreshKeepsTableColors proves the refresh command renders its table through
// the trusted writer, so the operator sees the same styling as list and cd.
func TestRefreshKeepsTableColors(t *testing.T) {
	cases := []struct {
		name, input string
		tables      int
	}{
		{"workspace", "refresh\nexit\n", 2},
		{"alias", "r\nexit\n", 2},
		{"endpoint", "cd ai-dev/endpoint-1\nrefresh\nexit\n", 3},
		// Entering session scope renders no table, so the startup table plus the
		// refreshed one prove the session-scope refresh is styled like list.
		{"session", "cd ai-dev/endpoint-1/res-1\nr\nexit\n", 2},
	}
	for _, c := range cases {
		for _, enabled := range []bool{true, false} {
			t.Run(c.name+map[bool]string{true: "/color", false: "/plain"}[enabled], func(t *testing.T) {
				var out, diagnostics strings.Builder
				err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader(c.input), &out, &diagnostics, InteractiveOptions{Color: ColorPolicy{Enabled: enabled}})
				if err != nil || diagnostics.Len() != 0 {
					t.Fatalf("err=%v diagnostics=%q", err, diagnostics.String())
				}
				text := out.String()
				if enabled {
					// The state column is dropped when colour is enabled, so the
					// row colour is proven by the green NO cell; "1 " with a
					// trailing space matches only the padded cell, not the
					// "running(1)" summary row.
					for _, token := range []string{ansiBoldCyan + "NO", ansiGreen + "1 "} {
						if got := strings.Count(text, token); got != c.tables {
							t.Fatalf("%q count=%d want=%d output=%q", token, got, c.tables, text)
						}
					}
				} else if strings.Contains(text, "\x1b") {
					t.Fatalf("plain output contains ANSI: %q", text)
				}
			})
		}
	}
}

// TestRefreshStillFiltersProviderANSI proves the trusted writer only carries the
// application's own styling: provider-derived cell text stays sanitized.
func TestRefreshStillFiltersProviderANSI(t *testing.T) {
	stub := singleHostStub()
	stub.endpoints[0].DisplayName = "host\x1b[31mRED\x1b[0m"
	stub.reports["endpoint-1"] = navInventory("sess\x1b[31mRED\x1b[0m", "generation-1")
	var out, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("refresh\nexit\n"), &out, &diagnostics, InteractiveOptions{Color: ColorPolicy{Enabled: true}})
	if err != nil || diagnostics.Len() != 0 {
		t.Fatalf("err=%v diagnostics=%q", err, diagnostics.String())
	}
	text := out.String()
	if strings.Contains(text, "\x1b[31m") {
		t.Fatalf("provider ANSI reached the terminal: %q", text)
	}
	if !strings.Contains(text, "provider-sessRED") {
		t.Fatalf("sanitized provider text missing: %q", text)
	}
}
