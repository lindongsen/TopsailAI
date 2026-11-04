package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestLocalEnvSyntax verifies literal values without executing expansions.
func TestLocalEnvSyntax(t *testing.T) {
	values, err := parseLocalEnv(strings.NewReader("# comment\nexport URL = http://localhost\nTOKEN='a#b' # comment\nEMPTY=\nDOUBLE=\"literal $HOME\"\nINLINE=value # comment\nURL=last\n"))
	if err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{"URL": "last", "TOKEN": "a#b", "EMPTY": "", "DOUBLE": "literal $HOME", "INLINE": "value"} {
		if values[key] != want {
			t.Fatalf("key=%s mismatch", key)
		}
	}
}

// TestLocalEnvRejectsInvalid avoids exposing contents in diagnostics.
func TestLocalEnvRejectsInvalid(t *testing.T) {
	for _, input := range []string{"bad-secret", "1BAD=secret", "=secret", "A='secret", "A=\"secret\" extra", "A=secret\x00"} {
		_, err := parseLocalEnv(strings.NewReader(input))
		if err == nil || strings.Contains(err.Error(), "secret") {
			t.Fatalf("unsafe diagnostic: %v", err)
		}
	}
	if _, err := parseLocalEnv(strings.NewReader(strings.Repeat("x", maxLocalEnvBytes+1))); err == nil {
		t.Fatal("oversized input accepted")
	}
}

// TestExecutableEnvPrecedence uses explicit lookup/set seams instead of global mutation.
func TestExecutableEnvPrecedence(t *testing.T) {
	dir, err := os.MkdirTemp(os.Getenv("TMPDIR"), "cli-env-")
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		t.Logf("cleanup task fixture %s", dir)
		if err := os.RemoveAll(dir); err != nil {
			t.Error(err)
		}
	}()
	executable := filepath.Join(dir, "cli")
	values := map[string]string{"KEEP": "", "OVERRIDE": "process"}
	lookup := func(key string) (string, bool) { v, ok := values[key]; return v, ok }
	set := func(key, value string) error { values[key] = value; return nil }
	if err := loadExecutableEnv(executable, lookup, set); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, ".env.local")
	if err := os.WriteFile(path, []byte("KEEP=file\nOVERRIDE=file\nNEW=file\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := loadExecutableEnv(executable, lookup, set); err != nil {
		t.Fatal(err)
	}
	if values["KEEP"] != "" || values["OVERRIDE"] != "process" || values["NEW"] != "file" {
		t.Fatal("precedence failure")
	}
	sentinel := errors.New("set failed")
	if err := loadExecutableEnv(executable, func(string) (string, bool) { return "", false }, func(string, string) error { return sentinel }); !errors.Is(err, sentinel) {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("NEW=changed\ninvalid\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := loadExecutableEnv(executable, lookup, set); err == nil || values["NEW"] != "file" {
		t.Fatal("invalid file mutated environment")
	}
}
