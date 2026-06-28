package main

import (
	"strings"
	"testing"
)

func TestColorEnabled(t *testing.T) {
	globalColorEnabled = true
	got := yellow("x")
	if !strings.Contains(got, "\033[") {
		t.Fatalf("expected ANSI code, got %q", got)
	}
}

func TestColorDisabled(t *testing.T) {
	globalColorEnabled = false
	got := yellow("x")
	if got != "x" {
		t.Fatalf("expected plain text, got %q", got)
	}
}

func TestColorize(t *testing.T) {
	globalColorEnabled = true
	got := colorize("x", "33")
	if !strings.HasPrefix(got, "\033[") || !strings.HasSuffix(got, "x\033[0m") {
		t.Fatalf("unexpected colorize output: %q", got)
	}
}

func TestStripANSI(t *testing.T) {
	globalColorEnabled = true
	colored := yellow("x")
	plain := stripANSI(colored)
	if plain != "x" {
		t.Fatalf("expected x, got %q", plain)
	}
}
