package node

import (
	"path/filepath"
	"testing"
)

// TestOverlapsConfigDirDetectsEveryDirection checks the three overlaps the
// startup rule refuses: the scope equals the config directory, the scope contains
// it, and the scope sits inside it.
//
// All three expose the Node's own credential files. The first two let a caller
// list the directory that holds them, which reports their names and sizes even
// though reading them is denied; the third is a directory whose parent holds the
// credentials.
func TestOverlapsConfigDirDetectsEveryDirection(t *testing.T) {
	base := filepath.Join(string(filepath.Separator), "srv", "node")
	configDir := filepath.Join(base, "config")

	cases := []struct {
		name      string
		scopePath string
		want      bool
	}{
		{name: "equal", scopePath: configDir, want: true},
		{name: "scope contains config", scopePath: base, want: true},
		{name: "scope is an ancestor of config", scopePath: filepath.Join(string(filepath.Separator), "srv"), want: true},
		{name: "scope inside config", scopePath: filepath.Join(configDir, "inner"), want: true},
		{name: "scope inside config deeply", scopePath: filepath.Join(configDir, "a", "b"), want: true},
		{name: "sibling", scopePath: filepath.Join(base, "project"), want: false},
		{name: "unrelated", scopePath: filepath.Join(string(filepath.Separator), "home", "me", "project"), want: false},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := overlapsConfigDir(testCase.scopePath, configDir); got != testCase.want {
				t.Fatalf("overlapsConfigDir(%q, %q) = %v, want %v", testCase.scopePath, configDir, got, testCase.want)
			}
		})
	}
}

// TestOverlapsConfigDirUsesASeparatorBoundary checks that a sibling whose name
// merely starts with the config directory's name is not treated as inside it.
//
// A string-prefix test would report `/srv/node/config-backup` as inside
// `/srv/node/config`, which would refuse a legitimate scope. The boundary is the
// separator, not the prefix.
func TestOverlapsConfigDirUsesASeparatorBoundary(t *testing.T) {
	base := filepath.Join(string(filepath.Separator), "srv", "node")
	configDir := filepath.Join(base, "config")

	siblings := []string{
		filepath.Join(base, "config-backup"),
		filepath.Join(base, "config2"),
		filepath.Join(base, "configuration"),
	}

	for _, sibling := range siblings {
		if overlapsConfigDir(sibling, configDir) {
			t.Fatalf("overlapsConfigDir(%q, %q) = true, want false for a sibling sharing only a name prefix", sibling, configDir)
		}
	}
}

// TestOverlapsConfigDirIgnoresRedundantSpellings checks that a trailing separator
// and a redundant dot segment do not hide an overlap.
//
// The comparison cleans both sides first, so a scope spelled with a trailing
// separator is still recognised as the config directory rather than slipping past
// the check.
func TestOverlapsConfigDirIgnoresRedundantSpellings(t *testing.T) {
	base := filepath.Join(string(filepath.Separator), "srv", "node")
	configDir := filepath.Join(base, "config")

	spellings := []string{
		configDir + string(filepath.Separator),
		filepath.Join(configDir, "."),
		configDir + string(filepath.Separator) + string(filepath.Separator),
	}

	for _, spelling := range spellings {
		if !overlapsConfigDir(spelling, configDir) {
			t.Fatalf("overlapsConfigDir(%q, %q) = false, want true for an equivalent spelling", spelling, configDir)
		}
	}
}

// TestOverlapsConfigDirWithoutAConfigDirectory checks that an empty config
// directory disables the rule.
//
// A caller that has no config directory states that by passing an empty value.
// Treating an empty value as a path would compare every scope against the empty
// string and refuse everything.
func TestOverlapsConfigDirWithoutAConfigDirectory(t *testing.T) {
	if overlapsConfigDir(filepath.Join(string(filepath.Separator), "srv", "node"), "") {
		t.Fatal("overlapsConfigDir(path, \"\") = true, want false when there is no config directory")
	}
}

// TestIsPathInsideRejectsTheParentItself checks that a path is not inside its own
// parent's parent, so the containment test cannot be satisfied by climbing.
func TestIsPathInsideRejectsTheParentItself(t *testing.T) {
	base := filepath.Join(string(filepath.Separator), "srv", "node")

	if isPathInside(base, base) != true {
		t.Fatal("isPathInside(base, base) = false, want true because a path contains itself")
	}
	if isPathInside(filepath.Dir(base), base) {
		t.Fatal("isPathInside(parent, base) = true, want false because a parent is not inside its child")
	}
}
