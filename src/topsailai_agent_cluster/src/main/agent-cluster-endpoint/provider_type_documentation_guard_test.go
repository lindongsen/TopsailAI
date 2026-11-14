package main

import (
	"os"
	"path/filepath"
	"regexp"
	"testing"
)

// This file guards the property that the operator-facing documentation names the
// same provider type the Endpoint actually registers. The adapter seam is gone, so
// a documented provider type is no longer a hint about which implementation runs:
// it is the only value an operator can copy into a node configuration, and a stale
// value makes the Endpoint refuse to start.
//
// The guard reads the documents as text instead of calling any function, because
// the regression it exists for lives in prose and configuration examples, not in
// code. No behavioural test can see it: the Endpoint never parses these files, so
// nothing fails at runtime when a document drifts. Only reading the text can assert
// that every documented value equals the registered name.
//
// It reuses the registry's existing convention rather than inventing a second one:
// adapterProviderType is the exact identifier passed to registry.RegisterType, so
// comparing against that constant means the document and the registry cannot
// diverge without this test failing.

// documentedProviderTypeFiles are the documents that carry a concrete
// "provider_type": "<value>" example. They are listed explicitly instead of being
// discovered by a repository-wide scan, because a scan would silently stop covering
// a file that was renamed, while an explicit list fails loudly when a path is gone.
var documentedProviderTypeFiles = []string{
	"conf/node.endpoint.conf.example",
	"tests/environment-variables/endpoint.feature.md",
	"docs/Environment_Variables.md",
}

// documentedProviderTypePattern matches a JSON provider_type assignment. The value
// is captured so the failure can name what the document actually says.
var documentedProviderTypePattern = regexp.MustCompile(`"provider_type"\s*:\s*"([^"]*)"`)

// repositoryRoot resolves the module root from this test file's directory. The test
// lives in src/main/agent-cluster-endpoint, so the root is two levels up. Resolving
// it relative to the source keeps the guard working from any checkout location.
func repositoryRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatalf("resolve repository root: %v", err)
	}
	return root
}

// documentedProviderTypeMatches returns every provider_type value found in one
// document, together with the line number it appeared on.
func documentedProviderTypeMatches(t *testing.T, path string) []providerTypeMatch {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read documented provider type file %q: %v", path, err)
	}
	matches := make([]providerTypeMatch, 0, 4)
	for lineIndex, line := range splitLines(string(content)) {
		for _, found := range documentedProviderTypePattern.FindAllStringSubmatch(line, -1) {
			matches = append(matches, providerTypeMatch{
				path:  path,
				line:  lineIndex + 1,
				value: found[1],
			})
		}
	}
	return matches
}

// providerTypeMatch is one documented provider_type value and where it was found.
type providerTypeMatch struct {
	path  string
	line  int
	value string
}

// splitLines splits a document into lines without keeping the terminator, so the
// reported line number matches what an editor shows.
func splitLines(content string) []string {
	lines := make([]string, 0, 64)
	current := make([]rune, 0, 128)
	for _, character := range content {
		if character == '\n' {
			lines = append(lines, string(current))
			current = current[:0]
			continue
		}
		current = append(current, character)
	}
	if len(current) > 0 {
		lines = append(lines, string(current))
	}
	return lines
}

// TestProviderTypeDocumentationNamesTheRegisteredImplementation proves every
// provider_type example in the operator-facing documents equals the name the
// Endpoint registers. A document that names a removed adapter would send an
// operator straight into a startup refusal.
func TestProviderTypeDocumentationNamesTheRegisteredImplementation(t *testing.T) {
	root := repositoryRoot(t)
	all := make([]providerTypeMatch, 0, 8)
	for _, relative := range documentedProviderTypeFiles {
		path := filepath.Join(root, relative)
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("documented provider type file %q is missing at %q: %v", relative, path, err)
		}
		all = append(all, documentedProviderTypeMatches(t, path)...)
	}

	// An empty scan must fail. Without this assertion the guard would pass on a
	// repository where every example was deleted or reworded, proving nothing while
	// reporting success.
	if len(all) == 0 {
		t.Fatalf("no provider_type example was found in %v, so this guard checked nothing", documentedProviderTypeFiles)
	}

	for _, match := range all {
		if match.value == adapterProviderType {
			continue
		}
		t.Errorf("%s:%d documents provider_type %q, but this Endpoint registers %q",
			match.path, match.line, match.value, adapterProviderType)
	}
}
