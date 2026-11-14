package main

// The documents in this repository are the only place an operator learns which
// JSON field names to write into a node configuration. A second spelling of the
// same concept produces no runtime failure anywhere: the Endpoint parses the
// canonical name, ignores the other one, and the operator sees a default instead
// of the value they set. Nothing in the code can notice, because the code never
// reads these documents. Only reading the text can assert that one concept has
// one spelling.
//
// The check matches a JSON field assignment, not a bare word. A document that
// states the concept does not exist ("there is no ... binding_id ... column") is
// a correct sentence and must not be reported, while a document that writes
// "binding_id": "x" is exactly the drift this guard exists for. Matching the
// assignment is what separates the two.

import (
	"os"
	"path/filepath"
	"regexp"
	"testing"
)

// documentedAdapterFieldFiles are the documents and configuration examples that
// carry a concrete adapter field assignment. They are listed explicitly instead
// of being discovered by a repository-wide scan, following the convention
// documentedProviderTypeFiles already established: a scan silently stops
// covering a file that was renamed, while an explicit list fails loudly when a
// path is gone.
var documentedAdapterFieldFiles = []string{
	"docs/API.md",
	"docs/agent-cluster-database.md",
	"docs/agent-cluster-protocol.md",
	"docs/agent-cluster-adapters.md",
	"docs/agent-cluster-architecture.md",
	"docs/Environment_Variables.md",
	"conf/node.endpoint.conf.example",
}

// canonicalAdapterField is the one spelling the Endpoint parses. It is the same
// name the protocol structs carry, so a document using it cannot disagree with
// the implementation.
const canonicalAdapterField = "adapter_id"

// alternateAdapterFieldPattern matches a JSON assignment of a second spelling for
// the adapter identity. The canonical name is deliberately absent from the
// alternation, because it is the spelling the documents are supposed to use.
var alternateAdapterFieldPattern = regexp.MustCompile(`"(?:binding_id|bindingId|binding-id|adapterId|adapter-id)"\s*:`)

// canonicalAdapterFieldPattern matches a JSON assignment of the canonical name.
// It exists so the guard can prove it read something: a scan that finds no
// canonical assignment either lost its file list or lost the documents, and in
// both cases the alternate-spelling check would pass while proving nothing.
var canonicalAdapterFieldPattern = regexp.MustCompile(`"` + canonicalAdapterField + `"\s*:`)

// adapterFieldMatch is one field assignment and where it was found.
type adapterFieldMatch struct {
	path string
	line int
	text string
}

// adapterFieldMatches returns every line of one document that matches the given
// pattern, together with the line number and the line text, so a failure names
// the exact place an operator would copy.
func adapterFieldMatches(t *testing.T, path string, pattern *regexp.Regexp) []adapterFieldMatch {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read documented adapter field file %q: %v", path, err)
	}
	matches := make([]adapterFieldMatch, 0, 4)
	for lineIndex, line := range splitLines(string(content)) {
		if !pattern.MatchString(line) {
			continue
		}
		matches = append(matches, adapterFieldMatch{
			path: path,
			line: lineIndex + 1,
			text: line,
		})
	}
	return matches
}

// TestDocumentedAdapterFieldSpelling proves the documents use one spelling for
// the adapter identity. A second spelling is invisible at runtime, so this is the
// only place the drift can be caught.
func TestDocumentedAdapterFieldSpelling(t *testing.T) {
	root := repositoryRoot(t)

	canonical := make([]adapterFieldMatch, 0, 8)
	alternate := make([]adapterFieldMatch, 0, 4)
	for _, relative := range documentedAdapterFieldFiles {
		path := filepath.Join(root, relative)
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("documented adapter field file %q is missing at %q: %v", relative, path, err)
		}
		canonical = append(canonical, adapterFieldMatches(t, path, canonicalAdapterFieldPattern)...)
		alternate = append(alternate, adapterFieldMatches(t, path, alternateAdapterFieldPattern)...)
	}

	// An empty canonical scan must fail. Without this assertion the guard would
	// pass on a repository where every example was deleted or reworded, proving
	// nothing while reporting success.
	if len(canonical) == 0 {
		t.Fatalf("no %q assignment was found in %v, so this guard checked nothing", canonicalAdapterField, documentedAdapterFieldFiles)
	}

	for _, match := range alternate {
		t.Errorf("%s:%d assigns a second spelling for the adapter identity, but the Endpoint parses %q: %s",
			match.path, match.line, canonicalAdapterField, match.text)
	}
}
