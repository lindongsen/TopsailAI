package main

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// clusterModulePath is the root module the Mock Provider must not depend on.
const clusterModulePath = "topsailai_agent_cluster"

// mockModulePath is the module path the Mock Provider declares for itself.
const mockModulePath = "agent-cluster-provider-mock"

// parseImports returns every import path declared by one Go file.
//
// The file is parsed rather than scanned as text, so a path mentioned in a
// comment is not mistaken for an import and an import written on its own line is
// not missed.
func parseImports(t *testing.T, path string) []string {
	t.Helper()
	file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
	if err != nil {
		t.Fatalf("parse %s: %v", path, err)
	}
	imports := make([]string, 0, len(file.Imports))
	for _, spec := range file.Imports {
		value, unquoteErr := strconv.Unquote(spec.Path.Value)
		if unquoteErr != nil {
			t.Fatalf("unquote import in %s: %v", path, unquoteErr)
		}
		imports = append(imports, value)
	}
	return imports
}

// TestMockImportsNoClusterPackage proves the Mock Provider reaches no package of
// the root module. The module boundary already makes such an import impossible to
// build, but a file that still names one would start compiling the moment the
// boundary was relaxed, so the absence is asserted rather than assumed.
func TestMockImportsNoClusterPackage(t *testing.T) {
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read the mock module directory: %v", err)
	}
	scanned := 0
	var offenders []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".go") {
			continue
		}
		scanned++
		for _, importPath := range parseImports(t, entry.Name()) {
			if importPath == clusterModulePath || strings.HasPrefix(importPath, clusterModulePath+"/") {
				offenders = append(offenders, entry.Name()+" imports "+importPath)
			}
		}
	}
	if scanned == 0 {
		t.Fatal("no Go file was scanned, so the boundary check proved nothing")
	}
	if len(offenders) > 0 {
		t.Fatalf("the Mock Provider imports a Cluster package, so it no longer builds independently: %v", offenders)
	}
}

// TestMockDeclaresItsOwnModule proves the Mock Provider is a separate module and
// that it does not redirect the root module through a replace directive. A
// replace directive would let the module import Cluster packages while still
// looking independent.
func TestMockDeclaresItsOwnModule(t *testing.T) {
	content, err := os.ReadFile("go.mod")
	if err != nil {
		t.Fatalf("read the mock go.mod: %v", err)
	}
	var moduleLine string
	var replaceLines []string
	for _, line := range strings.Split(string(content), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "module ") {
			moduleLine = trimmed
		}
		if strings.HasPrefix(trimmed, "replace ") || strings.HasPrefix(trimmed, "replace(") {
			replaceLines = append(replaceLines, trimmed)
		}
	}
	if moduleLine != "module "+mockModulePath {
		t.Fatalf("mock go.mod module line = %q, want %q", moduleLine, "module "+mockModulePath)
	}
	if len(replaceLines) > 0 {
		t.Fatalf("mock go.mod redirects another module through replace, so the boundary is not real: %v", replaceLines)
	}
}

// TestRootModuleDoesNotDependOnTheMock proves the dependency runs one way only.
// The Mock Provider is a test artifact, so the production module must not require
// it.
func TestRootModuleDoesNotDependOnTheMock(t *testing.T) {
	rootGoMod := filepath.Join("..", "..", "go.mod")
	content, err := os.ReadFile(rootGoMod)
	if err != nil {
		t.Fatalf("read the root go.mod: %v", err)
	}
	text := string(content)
	if strings.Contains(text, mockModulePath) {
		t.Fatalf("the root go.mod names the Mock Provider module %q, so production depends on a test artifact", mockModulePath)
	}
	if strings.Contains(text, "replace "+mockModulePath) {
		t.Fatalf("the root go.mod replaces the Mock Provider module %q", mockModulePath)
	}
}
