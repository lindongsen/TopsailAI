package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// workspacePath joins parts onto this provider workspace root.
//
// The workspace root is the directory that holds this module's go.mod, which is
// one level above the source directory. It is resolved by walking up to the
// module declaration rather than by counting levels, so a guard that reads a
// workspace file keeps working if the source directory is renamed or nested
// differently.
func workspacePath(t *testing.T, parts ...string) string {
	t.Helper()
	directory, err := os.Getwd()
	if err != nil {
		t.Fatalf("resolve the working directory: %v", err)
	}
	for {
		if moduleName(t, filepath.Join(directory, "go.mod")) == mockModulePath {
			return filepath.Join(append([]string{directory}, parts...)...)
		}
		parent := filepath.Dir(directory)
		if parent == directory {
			t.Fatalf("no go.mod declaring module %q was found above %s, so this guard cannot locate its own workspace", mockModulePath, mustWorkingDirectory(t))
		}
		directory = parent
	}
}

// clusterProjectRoot returns the Agent Cluster project directory.
//
// The guards in this workspace read files that belong to the cluster project,
// such as the root go.mod and the protocol schema. Those files are not part of
// this workspace, so their location has to be discovered rather than counted.
//
// Counting directory levels is what this function replaces. The previous guards
// used a literal "../../go.mod" style path, which silently pointed at a different
// directory the moment this workspace gained a source directory. A guard that
// cannot read its file fails, but a guard that reads the wrong file and finds
// nothing to complain about passes, and the two are indistinguishable from the
// test result alone.
//
// The root is found by module identity: walk up from the working directory until
// a go.mod declares the cluster module. Identity is used instead of a fixed depth
// because this workspace may be nested at any depth below the project, and a
// depth is a position rather than an identity.
func clusterProjectRoot(t *testing.T) string {
	t.Helper()
	directory, err := os.Getwd()
	if err != nil {
		t.Fatalf("resolve the working directory: %v", err)
	}
	for {
		if moduleName(t, filepath.Join(directory, "go.mod")) == clusterModulePath {
			return directory
		}
		parent := filepath.Dir(directory)
		if parent == directory {
			t.Fatalf("no go.mod declaring module %q was found above %s, so this guard cannot locate the cluster project", clusterModulePath, mustWorkingDirectory(t))
		}
		directory = parent
	}
}

// clusterPath joins parts onto the cluster project root.
func clusterPath(t *testing.T, parts ...string) string {
	t.Helper()
	return filepath.Join(append([]string{clusterProjectRoot(t)}, parts...)...)
}

// moduleName returns the module path declared by one go.mod file, or an empty
// string when the file is absent or declares no module.
func moduleName(t *testing.T, path string) string {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(content), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "module ") {
			return strings.TrimSpace(strings.TrimPrefix(trimmed, "module "))
		}
	}
	return ""
}

// mustWorkingDirectory returns the working directory for a failure message.
func mustWorkingDirectory(t *testing.T) string {
	t.Helper()
	directory, err := os.Getwd()
	if err != nil {
		return "(unknown)"
	}
	return directory
}
