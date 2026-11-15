package main

// The protocol document states which events refresh an Adapter descriptor and
// which event publishes a capability reload. Both sentences describe the
// implementation, and a document sentence is not executable: nothing fails when
// the code stops matching it, so an operator reads a trigger that no longer
// exists and waits for a reload that will never happen.
//
// These guards read the trigger set from the code that performs it instead of
// restating the sentence. The production call sites of RefreshDescriptors are
// counted, and the document is required to name the same single trigger.

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path/filepath"
	"strings"
	"testing"
)

// refreshCallSites returns every production trigger of RefreshDescriptors, keyed
// by the file that contains it.
//
// Test files are skipped because a test double is not a trigger. service.go is
// skipped because it holds the implementation: its own call delegates to the
// collector, so counting it would report the implementation as a second trigger
// and the guard would fail on correct code.
func refreshCallSites(t *testing.T, root string) map[string]int {
	t.Helper()
	sites := map[string]int{}
	for _, relative := range []string{
		"internal/endpoint/replace.go",
		"internal/endpoint/replace_file.go",
		"internal/endpoint/collector.go",
	} {
		path := filepath.Join(root, relative)
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatalf("parse %s: %v", relative, err)
		}
		ast.Inspect(file, func(node ast.Node) bool {
			call, ok := node.(*ast.CallExpr)
			if !ok {
				return true
			}
			selector, ok := call.Fun.(*ast.SelectorExpr)
			if !ok || selector.Sel.Name != "RefreshDescriptors" {
				return true
			}
			sites[relative]++
			return true
		})
	}
	return sites
}

// TestDescriptorRefreshHasOneProductionTrigger pins the trigger set the document
// describes: an Adapter replace, and nothing else.
func TestDescriptorRefreshHasOneProductionTrigger(t *testing.T) {
	root := repoRoot(t)
	sites := refreshCallSites(t, root)
	if len(sites) != 1 {
		t.Fatalf("RefreshDescriptors is called from %v, want exactly one production file", sites)
	}
	if sites["internal/endpoint/replace.go"] != 1 {
		t.Fatalf("RefreshDescriptors call sites = %v, want one call in internal/endpoint/replace.go", sites)
	}
}

// TestNoControlActionReloadTriggerExists proves the removed trigger is really
// absent, so the document's denial is a fact rather than a wish.
func TestNoControlActionReloadTriggerExists(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range []string{
		"internal/endpoint/replace.go",
		"internal/endpoint/replace_file.go",
		"internal/endpoint/collector.go",
	} {
		source := readRepoFile(t, root, relative)
		if strings.Contains(source, "ControlActionCatalog") || strings.Contains(source, "controlActionCatalog") {
			t.Fatalf("%s carries a control action catalog, so a reload trigger could exist", relative)
		}
	}
}

// TestProtocolDocumentNamesTheRealRefreshTrigger pins the two document sentences
// to the trigger set the code has.
func TestProtocolDocumentNamesTheRealRefreshTrigger(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, "docs/agent-cluster-protocol.md")
	for _, needle := range []string{
		"A control action approval reload is not a refresh trigger",
		"the only event that triggers it is a successful Adapter replace",
		"A control-action `SIGHUP` reload is not a trigger",
	} {
		if !strings.Contains(source, needle) {
			t.Fatalf("docs/agent-cluster-protocol.md must state %q", needle)
		}
	}
	for _, stale := range []string{
		"Endpoint policy reload and control\naction approval reload",
		"A successful control-action `SIGHUP` reload re-describes",
	} {
		if strings.Contains(source, stale) {
			t.Fatalf("docs/agent-cluster-protocol.md still claims the removed trigger %q", stale)
		}
	}
}
