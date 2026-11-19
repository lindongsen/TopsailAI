package nodehelp

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// sourceEnvironmentVariables returns every CONNECTOR_NODE_ variable the production code
// reads, found by scanning the source rather than by listing them here.
//
// The list is read from the source because a hand-written list is a second definition of
// the configuration surface, and the two drift apart silently: a variable added to the
// code and forgotten in the help is invisible to every other test, because nothing links
// the two. Test files are skipped, so a fixture such as CONNECTOR_NODE_UNRELATED_VALUE
// does not become a documented variable.
func sourceEnvironmentVariables(t *testing.T) []string {
	t.Helper()

	pattern := regexp.MustCompile(`CONNECTOR_NODE_[A-Z0-9_]+`)
	found := map[string]bool{}

	roots := []string{
		filepath.Join("..", "node"),
		filepath.Join("..", "..", "cmd", "connector-node"),
	}
	for _, root := range roots {
		entries, err := os.ReadDir(root)
		if err != nil {
			t.Fatalf("read %s: %v", root, err)
		}
		for _, entry := range entries {
			if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".go") {
				continue
			}
			if strings.HasSuffix(entry.Name(), "_test.go") {
				continue
			}
			content, err := os.ReadFile(filepath.Join(root, entry.Name()))
			if err != nil {
				t.Fatalf("read %s: %v", entry.Name(), err)
			}
			for _, match := range pattern.FindAllString(string(content), -1) {
				found[match] = true
			}
		}
	}

	names := make([]string, 0, len(found))
	for name := range found {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// TestMainHelpDocumentsEveryEnvironmentVariable is the guard that keeps the help honest.
//
// It fails when the code reads a variable the help does not name, which is the defect a
// reader cannot detect: the help is internally consistent and simply incomplete.
func TestMainHelpDocumentsEveryEnvironmentVariable(t *testing.T) {
	text := Main("connector-node")

	for _, name := range sourceEnvironmentVariables(t) {
		if !strings.Contains(text, name) {
			t.Errorf("Main help does not document %s, which the code reads", name)
		}
	}
}

// TestRunHelpDocumentsEveryEnvironmentVariable checks the page an operator reads when
// they are starting the Node, because that is where a missing variable costs the most.
func TestRunHelpDocumentsEveryEnvironmentVariable(t *testing.T) {
	text := Run("connector-node")

	for _, name := range sourceEnvironmentVariables(t) {
		if !strings.Contains(text, name) {
			t.Errorf("Run help does not document %s, which the code reads", name)
		}
	}
}

// TestMainHelpDocumentsEverySubcommand checks the synopsis against the commands the
// binary accepts.
//
// The list is written here rather than read from the source because the source expresses
// a subcommand as a string in a switch, which a scan cannot distinguish from any other
// string. The test therefore fails when a subcommand is added to this list without help,
// and the reviewer is the one who must add it: that is the point, because the reviewer is
// the only party who knows a new subcommand exists.
func TestMainHelpDocumentsEverySubcommand(t *testing.T) {
	text := Main("connector-node")

	subcommands := []string{"run", "id", "regenerate", "credential", "help"}
	for _, name := range subcommands {
		if !strings.Contains(text, "connector-node "+name) {
			t.Errorf("Main help has no synopsis line for %q", name)
		}
	}
}

// TestCredentialHelpDocumentsEveryCredentialSubcommand checks the three operations the
// credential command offers.
func TestCredentialHelpDocumentsEveryCredentialSubcommand(t *testing.T) {
	text := Credential("connector-node")

	for _, name := range []string{"add", "list", "remove"} {
		if !strings.Contains(text, "credential "+name) {
			t.Errorf("Credential help does not document %q", name)
		}
	}
}

// TestEveryPageNamesTheProgram checks that no page leaks the placeholder.
//
// The placeholder is substituted at print time, so a page that was written without it
// would print a synopsis the operator cannot type, and a page that kept it would print
// braces. Both are visible only in the output, which is why the check is on the output.
func TestEveryPageNamesTheProgram(t *testing.T) {
	pages := map[string]string{
		"Main":       Main("connector-node"),
		"Run":        Run("connector-node"),
		"ID":         ID("connector-node"),
		"Regenerate": Regenerate("connector-node"),
		"Credential": Credential("connector-node"),
	}

	for name, text := range pages {
		if strings.Contains(text, programPlaceholder) {
			t.Errorf("%s still contains the placeholder %q", name, programPlaceholder)
		}
		if !strings.Contains(text, "connector-node") {
			t.Errorf("%s does not name the program", name)
		}
	}
}

// TestEveryPageHasTheRequiredSections checks the shape every page shares.
//
// A page without an exit status leaves a script author guessing, and a page without a
// synopsis leaves a reader unable to type the command. Both are cheap to check and
// expensive to notice.
func TestEveryPageHasTheRequiredSections(t *testing.T) {
	pages := map[string]string{
		"Main":       Main("connector-node"),
		"Run":        Run("connector-node"),
		"ID":         ID("connector-node"),
		"Regenerate": Regenerate("connector-node"),
		"Credential": Credential("connector-node"),
	}

	for name, text := range pages {
		for _, section := range []string{"NAME", "SYNOPSIS", "DESCRIPTION", "EXIT STATUS"} {
			if !strings.Contains(text, section) {
				t.Errorf("%s has no %s section", name, section)
			}
		}
	}
}

// TestEveryPageStatesTheUsageStatus checks the promise a script depends on.
//
// The binaries exit 2 for a rejected command line, and the message begins with "usage:".
// A page that does not state it leaves the reader to discover the rule by experiment.
func TestEveryPageStatesTheUsageStatus(t *testing.T) {
	pages := map[string]string{
		"Main":       Main("connector-node"),
		"Run":        Run("connector-node"),
		"ID":         ID("connector-node"),
		"Regenerate": Regenerate("connector-node"),
		"Credential": Credential("connector-node"),
	}

	for name, text := range pages {
		if !strings.Contains(text, "usage:") {
			t.Errorf("%s does not mention the usage: prefix that accompanies status 2", name)
		}
	}
}

// TestPagesDoNotNameInternalPackages checks the audience rule.
//
// A reader of this help has the binary and nothing else. A page that explains a behaviour
// by naming a package, a struct or a function gives them a fact they cannot act on, and
// the sentence reads as helpful to whoever wrote it because they can see the code.
func TestPagesDoNotNameInternalPackages(t *testing.T) {
	pages := map[string]string{
		"Main":       Main("connector-node"),
		"Run":        Run("connector-node"),
		"ID":         ID("connector-node"),
		"Regenerate": Regenerate("connector-node"),
		"Credential": Credential("connector-node"),
	}

	forbidden := []string{"internal/", "os.Root", "func ", "struct"}
	for name, text := range pages {
		for _, word := range forbidden {
			if strings.Contains(text, word) {
				t.Errorf("%s names %q, which a reader without the source cannot act on", name, word)
			}
		}
	}
}
