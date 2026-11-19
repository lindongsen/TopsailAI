package serverhelp

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// sourceEnvironmentVariables returns every CONNECTOR_SERVER_ variable the production code
// reads, found by scanning the source rather than by listing them here.
//
// The list is read from the source because a hand-written list is a second definition of
// the configuration surface, and the two drift apart silently: a variable added to the
// code and forgotten in the help is invisible to every other test, because nothing links
// the two. Test files are skipped, so a fixture does not become a documented variable.
func sourceEnvironmentVariables(t *testing.T) []string {
	t.Helper()

	pattern := regexp.MustCompile(`CONNECTOR_SERVER_[A-Z0-9_]+`)
	found := map[string]bool{}

	roots := []string{
		filepath.Join("..", "server"),
		filepath.Join("..", "..", "cmd", "connector-server"),
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
	text := Main("connector-server")

	for _, name := range sourceEnvironmentVariables(t) {
		if !strings.Contains(text, name) {
			t.Errorf("Main help does not document %s, which the code reads", name)
		}
	}
}

// TestRunHelpDocumentsEveryEnvironmentVariable checks the page an operator reads when
// they are starting the Server, because that is where a missing variable costs the most.
func TestRunHelpDocumentsEveryEnvironmentVariable(t *testing.T) {
	text := Run("connector-server")

	for _, name := range sourceEnvironmentVariables(t) {
		if !strings.Contains(text, name) {
			t.Errorf("Run help does not document %s, which the code reads", name)
		}
	}
}

// TestMainHelpDocumentsEverySubcommand checks the synopsis against the commands the
// binary accepts.
func TestMainHelpDocumentsEverySubcommand(t *testing.T) {
	text := Main("connector-server")

	for _, name := range []string{"run", "cli", "help"} {
		if !strings.Contains(text, "connector-server "+name) {
			t.Errorf("Main help has no synopsis line for %q", name)
		}
	}
}

// TestMainHelpStatesThatNoNodeSecretIsHeld checks the property the whole design rests on.
//
// A reader of the Server's help is the person who could break it, by adding a variable
// that stores a Node credential. The page must say that no such variable exists, so the
// absence reads as a decision rather than as an omission.
func TestMainHelpStatesThatNoNodeSecretIsHeld(t *testing.T) {
	text := Main("connector-server")

	if !strings.Contains(text, "never receives") {
		t.Error("Main help does not state that the Server never receives a Node secret")
	}
	if !strings.Contains(text, "no scope list") {
		t.Error("Main help does not state that the Server holds no scope list")
	}
}

// TestCLIHelpPointsAtTheCLIsOwnHelp checks that the interface is documented once.
//
// The cli subcommand has a complete help of its own. Repeating it here would create two
// copies of one interface, and the copy that is not updated is the one a reader trusts.
func TestCLIHelpPointsAtTheCLIsOwnHelp(t *testing.T) {
	text := CLI("connector-server")

	if !strings.Contains(text, "cli --help") {
		t.Error("CLI help does not point at the cli subcommand's own help")
	}
}

// TestEveryPageNamesTheProgram checks that no page leaks the placeholder.
func TestEveryPageNamesTheProgram(t *testing.T) {
	pages := map[string]string{
		"Main": Main("connector-server"),
		"Run":  Run("connector-server"),
		"CLI":  CLI("connector-server"),
	}

	for name, text := range pages {
		if strings.Contains(text, programPlaceholder) {
			t.Errorf("%s still contains the placeholder %q", name, programPlaceholder)
		}
		if !strings.Contains(text, "connector-server") {
			t.Errorf("%s does not name the program", name)
		}
	}
}

// TestEveryPageHasTheRequiredSections checks the shape every page shares.
func TestEveryPageHasTheRequiredSections(t *testing.T) {
	pages := map[string]string{
		"Main": Main("connector-server"),
		"Run":  Run("connector-server"),
		"CLI":  CLI("connector-server"),
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
func TestEveryPageStatesTheUsageStatus(t *testing.T) {
	pages := map[string]string{
		"Main": Main("connector-server"),
		"Run":  Run("connector-server"),
		"CLI":  CLI("connector-server"),
	}

	for name, text := range pages {
		if !strings.Contains(text, "usage:") {
			t.Errorf("%s does not mention the usage: prefix that accompanies status 2", name)
		}
	}
}

// TestPagesDoNotNameInternalPackages checks the audience rule.
func TestPagesDoNotNameInternalPackages(t *testing.T) {
	pages := map[string]string{
		"Main": Main("connector-server"),
		"Run":  Run("connector-server"),
		"CLI":  CLI("connector-server"),
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
