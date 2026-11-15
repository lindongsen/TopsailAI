package main

import (
	"context"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
)

// This file guards the routing property behind the acceptance row "Configured
// Adapters route only through Generic CLI Adapter".
//
// adapter_seam_guard_test.go already pins the factory's shape: no provider-type
// parameter, no switch on a provider type, one RegisterType under
// adapterProviderType, and a validateProviderType with no fallback. Those guards
// answer "can configuration select an implementation". They do not answer "is the
// Generic CLI Adapter the only implementation that exists, and does every path
// reach it through the registry". Five gaps remained:
//
//  1. A second implementation directory under internal/adapter would not be
//     caught, because TestRemovedAdapterSeamsAreAbsent names two specific
//     removed paths rather than asserting the directory set.
//  2. A second genericcli.New call site would not be caught, because nothing
//     counts construction sites.
//  3. Registry.Prepare, the path activation and rollback use, has no test that
//     refuses an unregistered name; only Configure is covered.
//  4. replace.go could construct an adapter directly and no test would notice.
//  5. tests/harness/cluster.go is not in documentedProviderTypeFiles, so the
//     harness could name a removed provider type and every test would still pass.
//
// Each guard below closes one gap. None of them change production code: the
// property already holds, and the guards exist so it cannot stop holding.

// lastIdentName returns the final identifier in a selector chain, so r.Registry
// and Registry both report "Registry".
//
// A receiver is not always a bare identifier: replace.go holds the registry in a
// struct field and calls r.Registry.Prepare, so matching only *ast.Ident would
// report zero calls for a file that calls Prepare twice.
func lastIdentName(expr ast.Expr) string {
	switch value := expr.(type) {
	case *ast.Ident:
		return value.Name
	case *ast.SelectorExpr:
		return value.Sel.Name
	}
	return ""
}

// callPositions returns the byte offsets of every call whose callee matches the
// given receiver and method. An empty receiver matches a bare function call.
//
// Parsing rather than matching text matters here: adapter_factory.go mentions
// genericcli.New in a comment, so a substring count would report two construction
// sites for one call.
func callPositions(t *testing.T, file *ast.File, fset *token.FileSet, receiver, method string) []int {
	t.Helper()
	var offsets []int
	ast.Inspect(file, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		switch fun := call.Fun.(type) {
		case *ast.Ident:
			if receiver == "" && fun.Name == method {
				offsets = append(offsets, fset.Position(call.Pos()).Offset)
			}
		case *ast.SelectorExpr:
			if fun.Sel.Name == method && lastIdentName(fun.X) == receiver {
				offsets = append(offsets, fset.Position(call.Pos()).Offset)
			}
		}
		return true
	})
	return offsets
}

// parseRepoFile parses one repository file and returns its AST together with the
// file set, so a caller can report a position.
func parseRepoFile(t *testing.T, root, relative string) (*ast.File, *token.FileSet) {
	t.Helper()
	path := filepath.Join(root, relative)
	source, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", relative, err)
	}
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, path, source, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", relative, err)
	}
	return file, fset
}

// TestOnlyOneAdapterImplementationDirectoryExists proves internal/adapter holds
// exactly one implementation package.
//
// TestRemovedAdapterSeamsAreAbsent names the two paths that were removed. This
// guard asserts the whole set instead, so a third implementation added under a
// new name fails here rather than shipping as a second adapter path.
func TestOnlyOneAdapterImplementationDirectoryExists(t *testing.T) {
	root := repositoryRoot(t)
	entries, err := os.ReadDir(filepath.Join(root, "internal", "adapter"))
	if err != nil {
		t.Fatalf("read internal/adapter: %v", err)
	}
	var directories []string
	for _, entry := range entries {
		if entry.IsDir() {
			directories = append(directories, entry.Name())
		}
	}
	if len(directories) != 1 || directories[0] != "genericcli" {
		t.Fatalf("internal/adapter holds %v, want exactly [genericcli]: a second implementation directory is a second adapter path", directories)
	}
}

// TestGenericCLIIsConstructedAtOneCallSite proves the Generic CLI Adapter is
// built in exactly one place, and that the place is the factory.
//
// A second construction site is a second routing path: it would bypass the
// factory that the seam guards pin, and no guard on the factory's shape could
// see it.
func TestGenericCLIIsConstructedAtOneCallSite(t *testing.T) {
	root := repositoryRoot(t)
	type site struct {
		file   string
		offset int
	}
	var sites []site
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			switch entry.Name() {
			case ".git", ".tmp", ".task", "vendor":
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		source, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		fset := token.NewFileSet()
		file, parseErr := parser.ParseFile(fset, path, source, 0)
		if parseErr != nil {
			return parseErr
		}
		relative, relErr := filepath.Rel(root, path)
		if relErr != nil {
			return relErr
		}
		for _, offset := range callPositions(t, file, fset, "genericcli", "New") {
			sites = append(sites, site{file: relative, offset: offset})
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk the module: %v", err)
	}
	if len(sites) != 1 {
		t.Fatalf("genericcli.New is called at %d sites (%v), want exactly 1: a second construction site bypasses the factory", len(sites), sites)
	}
	want := filepath.Join("src", "main", "agent-cluster-endpoint", "adapter_factory.go")
	if sites[0].file != want {
		t.Fatalf("genericcli.New is called from %q, want %q: the only construction site must be the factory", sites[0].file, want)
	}
}

// TestRegistryPrepareRefusesAnUnregisteredName proves the path activation and
// rollback use refuses a name it does not know.
//
// Configure is covered by TestRegisterAdapterInstallsTheOnlyImplementation.
// Prepare is covered nowhere, and replace.go reaches the registry only through
// Prepare, so without this test the activation path could accept a removed name.
func TestRegistryPrepareRefusesAnUnregisteredName(t *testing.T) {
	registry := adapter.NewRegistry()
	if err := registry.RegisterType(adapterProviderType, func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return nil, nil
	}); err != nil {
		t.Fatalf("register %q: %v", adapterProviderType, err)
	}
	if _, err := registry.Prepare(context.Background(), adapter.Config{AdapterID: "probe", ProviderType: adapterProviderType}); err != nil {
		t.Fatalf("Prepare refused the registered name %q: %v", adapterProviderType, err)
	}
	for _, providerType := range []string{"topsailai", "fixture", "command"} {
		_, err := registry.Prepare(context.Background(), adapter.Config{AdapterID: "probe-" + providerType, ProviderType: providerType})
		if err == nil {
			t.Fatalf("Prepare accepted provider type %q, so activation can reach a removed implementation", providerType)
		}
		if !strings.Contains(err.Error(), "is not registered") {
			t.Fatalf("Prepare refused %q with %v, want a refusal by name: a factory error means the name reached an implementation", providerType, err)
		}
	}
}

// TestReplaceGoesThroughTheRegistry proves activation and rollback reach an
// adapter only through Registry.Prepare.
//
// A direct construction in replace.go would be a second routing path that no
// guard on the factory can see, because the factory would never run.
func TestReplaceGoesThroughTheRegistry(t *testing.T) {
	root := repositoryRoot(t)
	file, fset := parseRepoFile(t, root, filepath.Join("internal", "endpoint", "replace.go"))
	prepares := callPositions(t, file, fset, "Registry", "Prepare")
	if len(prepares) < 2 {
		t.Fatalf("replace.go calls Registry.Prepare %d times, want at least 2 (activation and rollback): %v", len(prepares), prepares)
	}
	if constructions := callPositions(t, file, fset, "genericcli", "New"); len(constructions) != 0 {
		t.Fatalf("replace.go constructs the Generic CLI Adapter directly at %v, so activation bypasses the registry", constructions)
	}
}

// TestHarnessConfiguresOnlyTheRegisteredProviderType proves the integration
// harness names the registered provider type.
//
// documentedProviderTypeFiles covers the operator-facing documents but not
// tests/harness/cluster.go, so the harness could name a removed type and every
// test would still pass while exercising nothing the Endpoint would accept.
func TestHarnessConfiguresOnlyTheRegisteredProviderType(t *testing.T) {
	root := repositoryRoot(t)
	text := readRepoFile(t, root, filepath.Join("tests", "harness", "cluster.go"))
	matches := documentedProviderTypePattern.FindAllStringSubmatch(text, -1)
	if len(matches) == 0 {
		t.Fatalf("tests/harness/cluster.go carries no provider_type assignment, so this guard no longer covers the harness")
	}
	for _, match := range matches {
		if match[1] != adapterProviderType {
			t.Fatalf("tests/harness/cluster.go names provider type %q, want %q: the harness would exercise a removed implementation", match[1], adapterProviderType)
		}
	}
}

// TestMainRegistersBeforeValidatingBeforeConfiguring proves the startup order.
//
// Validation must run before Configure, because Configure is what reaches a
// factory. If the order inverted, a removed name would reach the registry first
// and the actionable startup message would be lost.
func TestMainRegistersBeforeValidatingBeforeConfiguring(t *testing.T) {
	root := repositoryRoot(t)
	file, fset := parseRepoFile(t, root, filepath.Join("src", "main", "agent-cluster-endpoint", "main.go"))
	register := callPositions(t, file, fset, "", "registerAdapter")
	validate := callPositions(t, file, fset, "", "validateProviderType")
	configure := callPositions(t, file, fset, "registry", "Configure")
	if len(register) != 1 || len(validate) != 1 || len(configure) != 1 {
		t.Fatalf("main.go calls registerAdapter %d, validateProviderType %d, registry.Configure %d times, want exactly 1 each", len(register), len(validate), len(configure))
	}
	if !(register[0] < validate[0] && validate[0] < configure[0]) {
		t.Fatalf("main.go orders registerAdapter@%d, validateProviderType@%d, registry.Configure@%d; want registration, then validation, then configuration", register[0], validate[0], configure[0])
	}
}
