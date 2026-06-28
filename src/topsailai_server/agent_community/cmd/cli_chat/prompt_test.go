package main

import (
	"strings"
	"testing"
)

func TestPromptOutsideGroup(t *testing.T) {
	globalColorEnabled = false
	pm := NewPromptManager("alice")
	got := pm.String()
	if got != "acs@alice: " {
		t.Fatalf("unexpected prompt: %q", got)
	}
}

func TestPromptInsideGroup(t *testing.T) {
	globalColorEnabled = false
	pm := NewPromptManager("alice")
	pm.SetGroup("group-1")
	got := pm.String()
	if got != "acs@alice:group-1# " {
		t.Fatalf("unexpected prompt: %q", got)
	}
}

func TestPromptColored(t *testing.T) {
	globalColorEnabled = true
	pm := NewPromptManager("alice")
	got := pm.String()
	if !strings.Contains(got, "\033[") {
		t.Fatalf("expected colored prompt, got %q", got)
	}
}
