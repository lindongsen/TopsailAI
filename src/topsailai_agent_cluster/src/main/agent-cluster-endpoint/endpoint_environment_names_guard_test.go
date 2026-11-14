package main

// The Endpoint reads its configuration from environment variables, and the
// operator-facing reference in docs/Environment_Variables.md is the only place
// that says which ones exist. Nothing parses that document at runtime, so a
// variable the code reads but the document omits produces no failure anywhere:
// the operator never sets it, the feature it enables stays off, and the reason
// is invisible. The reverse is just as quiet: a name the document lists but the
// code never reads sends the operator to set a value that does nothing.
//
// The names are extracted from the source rather than restated here, because a
// hand-written list is a second copy of the same fact and the copy nobody reads
// is the one that drifts.

import (
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const endpointEnvironmentDocument = "docs/Environment_Variables.md"

const endpointConfigSource = "internal/config/config.go"

// endpointSourceRoots are the production source trees that may read an Endpoint
// environment variable. The list is explicit rather than a repository walk so a
// renamed tree fails loudly instead of silently shrinking the read set.
var endpointSourceRoots = []string{"internal", "src", "providers"}

// endpointEnvironmentReadPattern matches the direct read in the configuration
// loader, which is where an Endpoint input variable is declared.
var endpointEnvironmentReadPattern = regexp.MustCompile(`os\.Getenv\("(AGENT_CLUSTER_ENDPOINT_[A-Z0-9_]+)"\)`)

// endpointEnvironmentLiteralPattern matches any string literal naming an
// Endpoint variable, which covers the readers that keep the name in a constant
// instead of passing it to os.Getenv inline.
var endpointEnvironmentLiteralPattern = regexp.MustCompile(`"(AGENT_CLUSTER_ENDPOINT_[A-Z0-9_]+)"`)

// endpointTableRowPattern matches one row of the Endpoint variable table, whose
// first cell is the backticked variable name.
var endpointTableRowPattern = regexp.MustCompile("(?m)^\\|\\s*`(AGENT_CLUSTER_ENDPOINT_[A-Z0-9_]+)`")

// endpointSection returns the text of the "## Endpoint" section, stopping at the
// next sub-heading so the variable table is read without the prose that follows.
func endpointSection(t *testing.T, document string) string {
	t.Helper()
	start := strings.Index(document, "\n## Endpoint\n")
	if start < 0 {
		t.Fatalf("%s has no \"## Endpoint\" section, so this guard checked nothing", endpointEnvironmentDocument)
	}
	rest := document[start:]
	end := strings.Index(rest[1:], "\n### ")
	if end < 0 {
		return rest
	}
	return rest[:end+1]
}

// endpointTableNames returns the variable names listed in the Endpoint table.
func endpointTableNames(t *testing.T, section string) []string {
	t.Helper()
	matches := endpointTableRowPattern.FindAllStringSubmatch(section, -1)
	names := make([]string, 0, len(matches))
	for _, match := range matches {
		names = append(names, match[1])
	}
	return names
}

// endpointReadNames returns the Endpoint variables the configuration loader
// reads, paired with the line that reads them.
func endpointReadNames(t *testing.T, source string) map[string]int {
	t.Helper()
	names := map[string]int{}
	for _, match := range endpointEnvironmentReadPattern.FindAllStringSubmatchIndex(source, -1) {
		names[source[match[2]:match[3]]] = lineAt(source, match[0])
	}
	return names
}

// endpointSourceNames returns every Endpoint variable named by a production Go
// file, mapped to the file that names it. Test files are skipped because a test
// that sets a variable proves the test knows the name, not that the Endpoint
// reads it.
func endpointSourceNames(t *testing.T, root string) map[string]string {
	t.Helper()
	names := map[string]string{}
	for _, tree := range endpointSourceRoots {
		base := filepath.Join(root, tree)
		err := filepath.WalkDir(base, func(path string, entry fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			content, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			relative, err := filepath.Rel(root, path)
			if err != nil {
				return err
			}
			for _, match := range endpointEnvironmentLiteralPattern.FindAllStringSubmatch(string(content), -1) {
				if _, seen := names[match[1]]; !seen {
					names[match[1]] = relative
				}
			}
			return nil
		})
		if err != nil {
			t.Fatalf("walk %s: %v", base, err)
		}
	}
	return names
}

// endpointRemovedNames returns the names the document states are no longer read.
func endpointRemovedNames(t *testing.T, document string) map[string]bool {
	t.Helper()
	start := strings.Index(document, "\n### Removed Endpoint environment names\n")
	if start < 0 {
		t.Fatalf("%s has no \"### Removed Endpoint environment names\" section, so the reverse check cannot tell a removed name from an undocumented one", endpointEnvironmentDocument)
	}
	rest := document[start:]
	end := strings.Index(rest[1:], "\n### ")
	if end >= 0 {
		rest = rest[:end+1]
	}
	names := map[string]bool{}
	for _, match := range regexp.MustCompile("(?m)^\\|\\s*`(AGENT_CLUSTER_[A-Z0-9_]+)`").FindAllStringSubmatch(rest, -1) {
		names[match[1]] = true
	}
	if len(names) == 0 {
		t.Fatalf("%s lists no removed Endpoint name, so the reverse check cannot tell a removed name from an undocumented one", endpointEnvironmentDocument)
	}
	return names
}

// TestEndpointEnvironmentNamesAreDocumented pins both directions of the
// contract between the Endpoint's configuration loader and the operator
// reference: every variable the loader reads is documented, and every variable
// the Endpoint table lists is either read by production code or stated as
// removed. A name that satisfies neither direction is the defect this guard
// exists for, because it is invisible at runtime in both cases.
func TestEndpointEnvironmentNamesAreDocumented(t *testing.T) {
	root := repoRoot(t)
	document := readRepoFile(t, root, endpointEnvironmentDocument)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", endpointEnvironmentDocument)
	}
	source := readRepoFile(t, root, endpointConfigSource)

	read := endpointReadNames(t, source)
	if len(read) == 0 {
		t.Fatalf("%s reads no AGENT_CLUSTER_ENDPOINT_ variable, so the extraction pattern no longer matches the loader and this guard checked nothing", endpointConfigSource)
	}

	section := endpointSection(t, document)
	listed := endpointTableNames(t, section)
	if len(listed) == 0 {
		t.Fatalf("%s has no Endpoint variable table, so this guard checked nothing", endpointEnvironmentDocument)
	}
	documented := map[string]bool{}
	for _, name := range listed {
		documented[name] = true
	}

	// The forward check reads the table, not the whole document. A name that
	// appears only in a subsection heading or in prose is not documented as a
	// variable an operator can set, and searching the whole document would let
	// the heading satisfy the check for the row that is missing.
	missing := make([]string, 0, len(read))
	for name, line := range read {
		if !documented[name] {
			missing = append(missing, name+" (read at "+endpointConfigSource+":"+strconv.Itoa(line)+")")
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("%s does not list %d Endpoint variable(s) the loader reads in its Endpoint table: %s", endpointEnvironmentDocument, len(missing), strings.Join(missing, ", "))
	}

	named := endpointSourceNames(t, root)
	if len(named) == 0 {
		t.Fatalf("no production Go file names an AGENT_CLUSTER_ENDPOINT_ variable, so the reverse check checked nothing")
	}
	removed := endpointRemovedNames(t, document)

	unread := make([]string, 0, len(listed))
	for _, name := range listed {
		if _, ok := named[name]; ok {
			continue
		}
		if removed[name] {
			continue
		}
		unread = append(unread, name)
	}
	sort.Strings(unread)
	if len(unread) > 0 {
		t.Fatalf("%s lists %d Endpoint variable(s) that no production Go file reads and that are not stated as removed: %s", endpointEnvironmentDocument, len(unread), strings.Join(unread, ", "))
	}
}
