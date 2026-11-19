package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestValidateCommandDirAcceptsEmptyAndExistingDirectory proves the two accepted
// shapes: an unset value, which disables the endpoint-scope form, and an absolute
// path to a directory that exists.
func TestValidateCommandDirAcceptsEmptyAndExistingDirectory(t *testing.T) {
	if err := validateCommandDir(""); err != nil {
		t.Fatalf("empty command dir must be accepted, got %v", err)
	}
	directory := t.TempDir()
	if err := validateCommandDir(directory); err != nil {
		t.Fatalf("existing absolute directory must be accepted, got %v", err)
	}
}

// TestValidateCommandDirRejectsUnusableValues proves every rejection names the
// setting. A relative path is rejected because it would resolve against the
// process working directory, which is the implicit location this setting exists
// to replace; a missing path is rejected because argument confinement is computed
// relative to it.
func TestValidateCommandDirRejectsUnusableValues(t *testing.T) {
	file := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write fixture: %v", err)
	}
	cases := []struct {
		name      string
		directory string
	}{
		{name: "relative", directory: "relative/path"},
		{name: "missing", directory: filepath.Join(t.TempDir(), "absent")},
		{name: "not a directory", directory: file},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := validateCommandDir(testCase.directory)
			if err == nil {
				t.Fatalf("validateCommandDir accepted %q", testCase.directory)
			}
			if !strings.Contains(err.Error(), "command dir") {
				t.Fatalf("error must name the setting, got %v", err)
			}
		})
	}
}

// TestValidateRejectsConfiguredCommandDir proves the setting is validated through
// the startup path, not only through the helper. A guard that exists but is never
// called is indistinguishable from no guard.
func TestValidateRejectsConfiguredCommandDir(t *testing.T) {
	cfg := Defaults("agent-cluster-endpoint")
	cfg.CommandDir = "relative/path"
	if err := cfg.Validate(); err == nil {
		t.Fatal("Validate accepted a relative command dir")
	}
	cfg.CommandDir = t.TempDir()
	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate rejected an existing command dir: %v", err)
	}
}
