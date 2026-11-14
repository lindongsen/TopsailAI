package providerconformance

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// clusterModulePath is the module path every Cluster package shares.
const clusterModulePath = "topsailai_agent_cluster"

// servicePackages are the Cluster packages that would make conformance depend on
// a running service or a database. None of them may appear in the dependency
// closure of this package.
var servicePackages = []string{
	"internal/adapter",
	"internal/channel",
	"internal/client",
	"internal/config",
	"internal/endpoint",
	"internal/server",
	"internal/storage",
	"internal/tui",
}

// packageDir resolves a Cluster import path to its directory under the repository
// root, which is two levels above this package.
func packageDir(importPath string) string {
	relative := strings.TrimPrefix(importPath, clusterModulePath+"/")
	return filepath.Join(append([]string{"..", ".."}, strings.Split(relative, "/")...)...)
}

// directClusterImports returns the Cluster import paths of every Go file in dir.
// Test files are included only when includeTests is true, because a dependency's
// tests are never compiled into this package's test binary.
func directClusterImports(t *testing.T, dir string, includeTests bool) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read %s: %v", dir, err)
	}
	seen := map[string]bool{}
	var imports []string
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") {
			continue
		}
		if !includeTests && strings.HasSuffix(name, "_test.go") {
			continue
		}
		file, err := parser.ParseFile(token.NewFileSet(), filepath.Join(dir, name), nil, parser.ImportsOnly)
		if err != nil {
			t.Fatalf("parse %s: %v", name, err)
		}
		for _, spec := range file.Imports {
			path := strings.Trim(spec.Path.Value, `"`)
			if path != clusterModulePath && !strings.HasPrefix(path, clusterModulePath+"/") {
				continue
			}
			if seen[path] {
				continue
			}
			seen[path] = true
			imports = append(imports, path)
		}
	}
	sort.Strings(imports)
	return imports
}

// TestConformanceDependencyClosureExcludesServices walks the Cluster imports of
// this package and of every Cluster package it reaches, and fails when a service
// or database package appears anywhere in that closure. A direct import check
// alone would miss a dependency that starts importing a service later.
func TestConformanceDependencyClosureExcludesServices(t *testing.T) {
	const root = "."
	visited := map[string]bool{}
	queue := []string{root}
	var closure []string
	for len(queue) > 0 {
		dir := queue[0]
		queue = queue[1:]
		includeTests := dir == root
		for _, path := range directClusterImports(t, dir, includeTests) {
			if visited[path] {
				continue
			}
			visited[path] = true
			closure = append(closure, path)
			queue = append(queue, packageDir(path))
		}
	}
	sort.Strings(closure)
	if len(closure) == 0 {
		t.Fatal("the dependency closure is empty, so the walk never read an import")
	}
	for _, forbidden := range servicePackages {
		wanted := clusterModulePath + "/" + forbidden
		for _, path := range closure {
			if path == wanted || strings.HasPrefix(path, wanted+"/") {
				t.Fatalf("the conformance dependency closure contains %q, so conformance needs a service or a database: %v", path, closure)
			}
		}
	}
	t.Logf("conformance dependency closure: %v", closure)
}

// TestConformanceStartsOnlyTheProviderExecutable proves the package launches one
// process and that the process is the configured Provider CLI, not a Cluster
// service or a database client.
func TestConformanceStartsOnlyTheProviderExecutable(t *testing.T) {
	source := repoText(t, "internal", "providerconformance", "runner.go")
	if count := strings.Count(source, "exec.Command("); count != 1 {
		t.Fatalf("runner.go starts %d processes, so conformance may launch more than the Provider CLI", count)
	}
	if !strings.Contains(source, "exec.Command(r.config.Executable)") {
		t.Fatal("runner.go does not start the configured Provider executable")
	}
	for _, name := range []string{"agent-cluster-server", "agent-cluster-endpoint", "psql", "sqlite3", "docker"} {
		if strings.Contains(source, name) {
			t.Fatalf("runner.go mentions %q, so conformance may depend on a service or a database", name)
		}
	}
}

// TestConformancePackageDocumentStatesIsolation pins the package contract that
// the isolation requirement rests on, so the sentence cannot disappear while the
// behaviour is still assumed.
func TestConformancePackageDocumentStatesIsolation(t *testing.T) {
	source := repoText(t, "internal", "providerconformance", "runner.go")
	normalized := strings.Join(strings.Fields(strings.ReplaceAll(source, "//", " ")), " ")
	want := "without starting an Endpoint, Server, channel or Cluster database."
	if !strings.Contains(normalized, want) {
		t.Fatalf("the package document no longer states %q", want)
	}
}

// makeRecipe returns the tab-indented recipe lines of one Makefile target.
func makeRecipe(t *testing.T, makefile, target string) string {
	t.Helper()
	lines := strings.Split(makefile, "\n")
	for index, line := range lines {
		if line != target+":" {
			continue
		}
		var recipe []string
		for _, following := range lines[index+1:] {
			if !strings.HasPrefix(following, "\t") {
				break
			}
			recipe = append(recipe, following)
		}
		return strings.Join(recipe, "\n")
	}
	return ""
}

// localRecipeVariables are the only environment variables the conformance recipe
// may set. They all describe the local Provider CLI process or the Go toolchain.
// A whitelist is used rather than a list of forbidden names, because a new
// service address such as AGENT_CLUSTER_SERVER_URL would otherwise pass a
// blacklist that only names binaries and database clients.
var localRecipeVariables = map[string]bool{
	"GOCACHE":                           true,
	"GOTMPDIR":                          true,
	"TMPDIR":                            true,
	"AGENT_CLUSTER_MOCK_EXECUTABLE":     true,
	"AGENT_CLUSTER_PROVIDER_SESSION_ID": true,
	"AGENT_CLUSTER_PROVIDER_EXECUTABLE": true,
	"AGENT_CLUSTER_PROVIDER_ADAPTER_ID": true,
}

// recipeAssignments returns every NAME=value variable name the recipe sets.
func recipeAssignments(recipe string) []string {
	seen := map[string]bool{}
	var names []string
	for _, line := range strings.Split(recipe, "\n") {
		for _, field := range strings.Fields(line) {
			index := strings.Index(field, "=")
			if index <= 0 {
				continue
			}
			name := field[:index]
			if strings.HasPrefix(name, "-") || strings.ContainsAny(name, "$/.:") {
				continue
			}
			if seen[name] {
				continue
			}
			seen[name] = true
			names = append(names, name)
		}
	}
	sort.Strings(names)
	return names
}

// TestConformanceMakeTargetBuildsOnlyTheMock proves the conformance target builds
// the Mock Provider module and runs this package, and starts no service.
func TestConformanceMakeTargetBuildsOnlyTheMock(t *testing.T) {
	recipe := makeRecipe(t, repoText(t, "Makefile"), "test-conformance")
	if recipe == "" {
		t.Fatal("the Makefile has no test-conformance recipe")
	}
	for _, want := range []string{"providers/mock", "go test -count=1 ./internal/providerconformance"} {
		if !strings.Contains(recipe, want) {
			t.Fatalf("the test-conformance recipe does not contain %q: %s", want, recipe)
		}
	}
	for _, forbidden := range []string{"agent-cluster-server", "agent-cluster-endpoint", "docker", "psql", "postgres", "sqlite"} {
		if strings.Contains(recipe, forbidden) {
			t.Fatalf("the test-conformance recipe mentions %q, so conformance starts a service or a database: %s", forbidden, recipe)
		}
	}
	assignments := recipeAssignments(recipe)
	if len(assignments) == 0 {
		t.Fatal("the test-conformance recipe sets no variable, so the assignment scan read nothing")
	}
	for _, name := range assignments {
		if !localRecipeVariables[name] {
			t.Fatalf("the test-conformance recipe sets %q, which is not a local Provider CLI or Go toolchain variable: %v", name, assignments)
		}
	}
	t.Logf("test-conformance recipe variables: %v", assignments)
}
