package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// This file guards the structural property that made the adapter seam removable:
// the Endpoint ships exactly one adapter implementation, so a configured provider
// type can only be compared against a name. It must never again select code.
//
// The guards read the source instead of calling the functions, because the
// regression they exist for is a shape, not a value. A behavioural test can only
// observe the branch that the current configuration happens to take; a switch that
// is unreachable today becomes reachable the moment an operator writes a different
// provider type, and no test that configures one adapter can see that. Parsing the
// file is the only way to assert "there is no branch here at all".
//
// Every guard reuses the registry's existing convention: a provider type is a key
// passed to RegisterType, and an unknown key is refused by the registry. None of
// them introduce a second registration mechanism or a second refusal path.

// providerTypeNames are the names that must never appear as a switch case. The
// first is the shipped name; the rest are the removed adapters. A case on any of
// them is the seam this file exists to prevent.
var providerTypeNames = []string{"genericcli", "topsailai", "fixture", "command"}

// nodeText returns the source text spanned by one node.
func nodeText(fset *token.FileSet, source []byte, node ast.Node) string {
	if node == nil {
		return ""
	}
	start := fset.Position(node.Pos()).Offset
	end := fset.Position(node.End()).Offset
	if start < 0 || end > len(source) || start >= end {
		return ""
	}
	return string(source[start:end])
}

// findFunc returns the declaration of one function in a file.
func findFunc(t *testing.T, file *ast.File, name string) *ast.FuncDecl {
	t.Helper()
	for _, decl := range file.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Name == nil || fn.Name.Name != name {
			continue
		}
		return fn
	}
	t.Fatalf("function %q is not declared in this file", name)
	return nil
}

// TestAdapterFactoryTakesNoProviderTypeParameter proves the registration cannot be
// told which implementation to install.
//
// A string parameter is the seam: it is what a switch would branch on. Requiring
// that no parameter is a string means a future change cannot reintroduce the seam
// without also changing this signature, which is a visible, reviewable act rather
// than a new case that silently becomes reachable through configuration.
func TestAdapterFactoryTakesNoProviderTypeParameter(t *testing.T) {
	fset := token.NewFileSet()
	source, err := os.ReadFile("adapter_factory.go")
	if err != nil {
		t.Fatalf("read adapter_factory.go: %v", err)
	}
	file, err := parser.ParseFile(fset, "adapter_factory.go", source, parser.ParseComments)
	if err != nil {
		t.Fatalf("parse adapter_factory.go: %v", err)
	}
	fn := findFunc(t, file, "registerAdapter")
	params := fn.Type.Params.List
	// Four parameter groups: the registry, the store, the configured detail bound
	// and the configured command directory. The count is pinned so a new parameter
	// is a deliberate, reviewable change rather than something that appears
	// silently; the string check below is what actually protects the seam this
	// guard exists for.
	if len(params) != 4 {
		t.Fatalf("registerAdapter takes %d parameter groups, want 4 (registry, store, detail bound and command directory): %s",
			len(params), nodeText(fset, source, fn.Type))
	}
	// allowedStringParams names the string parameters that are not a provider-type
	// seam. A filesystem path cannot select an implementation: it is a location the
	// operator configured, and the adapter uses it as a working directory rather
	// than branching on it. Every other string parameter is still refused, and a
	// second string parameter is refused even when it is named here, so the
	// exception cannot grow into a general allowance.
	allowedStringParams := map[string]bool{"commandDir": true}
	stringParams := 0
	for _, field := range params {
		// A variadic string is the same seam in a different spelling, so the
		// ellipsis is unwrapped before the type is inspected.
		fieldType := field.Type
		if ellipsis, ok := fieldType.(*ast.Ellipsis); ok {
			fieldType = ellipsis.Elt
		}
		if ident, ok := fieldType.(*ast.Ident); ok && ident.Name == "string" {
			stringParams++
			if stringParams > 1 {
				t.Fatalf("registerAdapter takes more than one string parameter, so a provider type can select an implementation: %s",
					nodeText(fset, source, fn.Type))
			}
			allowed := false
			for _, name := range field.Names {
				if allowedStringParams[name.Name] {
					allowed = true
				}
			}
			if !allowed {
				t.Fatalf("registerAdapter takes a string parameter that is not a configured path, so a provider type can select an implementation: %s",
					nodeText(fset, source, fn.Type))
			}
		}
		for _, name := range field.Names {
			if strings.Contains(strings.ToLower(name.Name), "provider") {
				t.Fatalf("registerAdapter takes a parameter named %q, which is the seam this guard exists for",
					name.Name)
			}
		}
	}
}

// TestAdapterFactoryBranchesOnNoProviderType proves no switch in the factory can
// dispatch on a provider type.
//
// Two shapes are refused: a switch whose tag mentions a provider type, and any case
// clause whose value is one of the provider type names. The second catches the
// indirect form, where the tag is a local variable that was assigned from the
// configuration earlier in the function.
func TestAdapterFactoryBranchesOnNoProviderType(t *testing.T) {
	fset := token.NewFileSet()
	source, err := os.ReadFile("adapter_factory.go")
	if err != nil {
		t.Fatalf("read adapter_factory.go: %v", err)
	}
	file, err := parser.ParseFile(fset, "adapter_factory.go", source, parser.ParseComments)
	if err != nil {
		t.Fatalf("parse adapter_factory.go: %v", err)
	}
	ast.Inspect(file, func(node ast.Node) bool {
		stmt, ok := node.(*ast.SwitchStmt)
		if !ok {
			return true
		}
		tag := strings.ToLower(nodeText(fset, source, stmt.Tag))
		if strings.Contains(tag, "providertype") {
			t.Fatalf("the adapter factory switches on %q, so configuration can select an implementation: %s",
				nodeText(fset, source, stmt.Tag), nodeText(fset, source, stmt))
		}
		for _, clause := range stmt.Body.List {
			caseClause, ok := clause.(*ast.CaseClause)
			if !ok {
				continue
			}
			for _, expr := range caseClause.List {
				literal, ok := expr.(*ast.BasicLit)
				if !ok || literal.Kind != token.STRING {
					continue
				}
				value := strings.Trim(literal.Value, `"`)
				for _, name := range providerTypeNames {
					if value == name {
						t.Fatalf("the adapter factory has a case for provider type %q, so configuration can select an implementation: %s",
							value, nodeText(fset, source, stmt))
					}
				}
			}
		}
		return true
	})
}

// TestAdapterFactoryRegistersThroughTheRegistryName proves the factory reuses the
// registry's existing convention instead of a parallel one.
//
// The registry already refuses an unknown provider type on Configure and Prepare.
// Registering under adapterProviderType is what makes that refusal the only gate,
// so there is one place that decides whether a name is acceptable. A second
// registration mechanism, or a literal name here, would create a second gate that
// could disagree with the first.
func TestAdapterFactoryRegistersThroughTheRegistryName(t *testing.T) {
	fset := token.NewFileSet()
	source, err := os.ReadFile("adapter_factory.go")
	if err != nil {
		t.Fatalf("read adapter_factory.go: %v", err)
	}
	file, err := parser.ParseFile(fset, "adapter_factory.go", source, parser.ParseComments)
	if err != nil {
		t.Fatalf("parse adapter_factory.go: %v", err)
	}
	fn := findFunc(t, file, "registerAdapter")
	registrations := 0
	ast.Inspect(fn, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		selector, ok := call.Fun.(*ast.SelectorExpr)
		if !ok || selector.Sel.Name != "RegisterType" {
			return true
		}
		registrations++
		if len(call.Args) != 2 {
			t.Fatalf("RegisterType is called with %d arguments, want 2: %s",
				len(call.Args), nodeText(fset, source, call))
		}
		ident, ok := call.Args[0].(*ast.Ident)
		if !ok || ident.Name != "adapterProviderType" {
			t.Fatalf("RegisterType is called with %q instead of adapterProviderType, so the registered name and the validated name can diverge: %s",
				nodeText(fset, source, call.Args[0]), nodeText(fset, source, call))
		}
		return true
	})
	if registrations != 1 {
		t.Fatalf("registerAdapter registers %d provider types, want exactly 1", registrations)
	}
}

// TestValidateProviderTypeHasNoFallbackPath proves the name check cannot be
// bypassed.
//
// The function must have exactly two returns: nil when the configured name equals
// adapterProviderType, and an error otherwise. A third return is a fallback, and a
// fallback is the seam returning in a different shape: it would accept a name the
// registry refuses, so the startup check and the registry would disagree about
// which configurations are valid.
func TestValidateProviderTypeHasNoFallbackPath(t *testing.T) {
	fset := token.NewFileSet()
	source, err := os.ReadFile("adapter_factory.go")
	if err != nil {
		t.Fatalf("read adapter_factory.go: %v", err)
	}
	file, err := parser.ParseFile(fset, "adapter_factory.go", source, parser.ParseComments)
	if err != nil {
		t.Fatalf("parse adapter_factory.go: %v", err)
	}
	fn := findFunc(t, file, "validateProviderType")
	returns := 0
	equality := false
	ast.Inspect(fn, func(node ast.Node) bool {
		switch typed := node.(type) {
		case *ast.ReturnStmt:
			returns++
		case *ast.BinaryExpr:
			if typed.Op != token.EQL {
				return true
			}
			left := nodeText(fset, source, typed.X)
			right := nodeText(fset, source, typed.Y)
			if (left == "providerType" && right == "adapterProviderType") ||
				(left == "adapterProviderType" && right == "providerType") {
				equality = true
			}
		}
		return true
	})
	if returns != 2 {
		t.Fatalf("validateProviderType has %d returns, want exactly 2 (accept the shipped name, refuse everything else): %s",
			returns, nodeText(fset, source, fn))
	}
	if !equality {
		t.Fatalf("validateProviderType does not compare providerType with adapterProviderType, so it accepts something other than the registered name: %s",
			nodeText(fset, source, fn))
	}
}

// TestMainRegistersTheAdapterWithoutAProviderType proves the call site cannot pass
// a provider type either.
//
// Guarding the signature alone is not enough: a caller could pass a value through a
// package-level variable. Requiring the call to have exactly four arguments pins the
// call site to the same shape as the signature.
func TestMainRegistersTheAdapterWithoutAProviderType(t *testing.T) {
	fset := token.NewFileSet()
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatalf("read main.go: %v", err)
	}
	file, err := parser.ParseFile(fset, "main.go", source, parser.ParseComments)
	if err != nil {
		t.Fatalf("parse main.go: %v", err)
	}
	calls := 0
	ast.Inspect(file, func(node ast.Node) bool {
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		ident, ok := call.Fun.(*ast.Ident)
		if !ok || ident.Name != "registerAdapter" {
			return true
		}
		calls++
		if len(call.Args) != 4 {
			t.Fatalf("registerAdapter is called with %d arguments, want 4 (registry, store, detail bound and command directory): %s",
				len(call.Args), nodeText(fset, source, call))
		}
		return true
	})
	if calls != 1 {
		t.Fatalf("main registers the adapter %d times, want exactly 1", calls)
	}
}

// removedSeams are the packages that used to provide a second adapter path. Each
// one is a dual seam: a second way to reach a provider, reachable through
// configuration or through a direct construction that bypassed the registry.
var removedSeams = []string{
	"internal/adapter/topsailai",
	"internal/controlaction",
}

// TestRemovedAdapterSeamsAreAbsent proves no second adapter path exists on disk.
//
// A directory that is gone cannot be imported, so this is the structural form of
// "there is no dual seam". It is checked on disk rather than by grepping imports
// because an unused package still compiles and still ships, and a package that
// exists is a package the next change can start using again.
func TestRemovedAdapterSeamsAreAbsent(t *testing.T) {
	for _, seam := range removedSeams {
		path := filepath.Join("..", "..", "..", seam)
		if _, err := os.Stat(path); err == nil {
			t.Fatalf("the removed adapter seam %q exists again, so a second adapter path can be reintroduced", seam)
		} else if !os.IsNotExist(err) {
			t.Fatalf("stat %q: %v", seam, err)
		}
	}
}

// TestNoSourceImportsARemovedSeam proves nothing reaches a removed seam by import.
//
// The directory check above catches a package that came back. This one catches the
// other direction: a file that still names the import, which would fail to build
// today but would silently start working the moment the package returned. Together
// they pin both halves of "no dual seam".
func TestNoSourceImportsARemovedSeam(t *testing.T) {
	root := filepath.Join("..", "..", "..")
	var offenders []string
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			name := entry.Name()
			if name == ".git" || name == ".tmp" || name == ".task" || name == "vendor" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") {
			return nil
		}
		source, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		text := string(source)
		for _, seam := range removedSeams {
			if strings.Contains(text, `"topsailai_agent_cluster/`+seam+`"`) {
				offenders = append(offenders, path+" imports "+seam)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk the module: %v", err)
	}
	if len(offenders) > 0 {
		t.Fatalf("a removed adapter seam is still imported, so a second adapter path is wired in: %v", offenders)
	}
}
