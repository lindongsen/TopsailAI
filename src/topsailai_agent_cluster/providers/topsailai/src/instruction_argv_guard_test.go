package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestInstructionArgvIsBuiltInOnePlace proves the provider instruction argv has a
// single production spelling.
//
// Every instruction this executable invokes goes through the same provider
// surface, so a second copy of the argv would let two call sites drift in flag
// order or in the payload envelope. That drift would not fail a build; it would
// surface as a provider parse failure at runtime, which is exactly the kind of
// defect a guard must catch instead of a reviewer.
func TestInstructionArgvIsBuiltInOnePlace(t *testing.T) {
	const spelling = `"runtime", "control", "call_instruction"`
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read the package directory: %v", err)
	}
	var owners []string
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		content, err := os.ReadFile(filepath.Clean(name))
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if strings.Contains(string(content), spelling) {
			owners = append(owners, name)
		}
	}
	if len(owners) != 1 {
		t.Fatalf("the instruction argv is spelled in %v, want exactly one production file", owners)
	}
	if owners[0] != "model_current.go" {
		t.Fatalf("the instruction argv is spelled in %s, want model_current.go", owners[0])
	}
}
