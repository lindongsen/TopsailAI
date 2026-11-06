package tui

import (
	"context"
	"strings"
	"testing"
)

// TestNavigationListColors checks every automatic table, not just the prompt or startup table.
func TestNavigationListColors(t *testing.T) {
	cases := []struct {
		name, input string
		tables      int
	}{
		{"workspace", "cd ai-dev/endpoint-1/res-1\ncd\nquit\n", 2},
		{"root", "cd ai-dev/endpoint-1/res-1\ncd /\nquit\n", 2},
		{"parent", "cd ai-dev/endpoint-1/res-1\ncd ..\nquit\n", 2},
		{"endpoint", "cd ai-dev/endpoint-1\nquit\n", 2},
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

// TestNavigationConflictStillFiltersExternalANSI preserves the untrusted-text boundary.
func TestNavigationConflictStillFiltersExternalANSI(t *testing.T) {
	stub := conflictStub()
	for i := range stub.endpoints {
		stub.endpoints[i].DisplayName = "host\x1b[31mRED\x1b[0m"
	}
	var out, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("cd ai-dev\ncancel\nquit\n"), &out, &diagnostics, InteractiveOptions{Color: ColorPolicy{Enabled: true}})
	if err != nil || diagnostics.Len() != 0 {
		t.Fatalf("err=%v diagnostics=%q", err, diagnostics.String())
	}
	if strings.Contains(out.String(), "\x1b[31m") || !strings.Contains(out.String(), "hostRED") {
		t.Fatalf("unsafe conflict output: %q", out.String())
	}
}
