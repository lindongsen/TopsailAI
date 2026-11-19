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

// TestMainHelpStatesThatAPathMustBeAbsolute checks that every variable the code refuses
// when relative is documented as needing an absolute path.
//
// The defect this guards against was measured, not imagined: CONNECTOR_NODE_CONFIG_DIR
// was refused with "is relative; a relative path resolves differently per launch", and
// the help said nothing about it. An operator who writes CONFIG_DIR=./config gets a
// startup failure whose message names a rule the help never stated, so the help is the
// place the rule has to appear.
//
// The list is written here rather than derived from the source because the source
// expresses the rule as a filepath.IsAbs call inside a resolver, which a scan cannot
// attribute to a variable name. A reviewer adding a path variable must add it here, and
// the failure message names the variable so the omission is obvious.
func TestMainHelpStatesThatAPathMustBeAbsolute(t *testing.T) {
	text := Main("connector-node")

	// Every CONNECTOR_NODE_ variable the code passes through filepath.IsAbs.
	absolute := []string{
		"CONNECTOR_NODE_CONFIG_DIR",
		"CONNECTOR_NODE_CREDENTIALS_FILE",
		"CONNECTOR_NODE_POLICY_FILE",
	}

	for _, name := range absolute {
		entry := entryFor(t, text, name)
		if !statesTheAbsoluteRule(entry) {
			t.Errorf("%s is refused when relative, but its help entry does not say so:\n%s", name, entry)
		}
	}
}

// statesTheAbsoluteRule reports whether an entry tells the reader that a relative path is
// not accepted.
//
// Two spellings state the same rule: "must be an absolute path" and "a relative path is
// refused". Both are actionable, and forcing one wording would be a test that enforces a
// style rather than a rule, which is the kind of test that gets deleted instead of fixed.
// What must not pass is an entry that says neither, because then the operator learns the
// rule only from a startup failure.
func statesTheAbsoluteRule(entry string) bool {
	return strings.Contains(entry, "absolute") || strings.Contains(entry, "relative")
}

// entryFor returns the help entry for one environment variable, from its name to the next
// blank line.
//
// The entry is isolated rather than searched in the whole page, because "absolute" appears
// elsewhere on this page in the policy-file description. A whole-page search would pass on
// that unrelated sentence and prove nothing about this variable.
func entryFor(t *testing.T, text, name string) string {
	t.Helper()

	lines := strings.Split(text, "\n")
	start := -1
	for index, line := range lines {
		if strings.TrimSpace(line) == name {
			start = index
			break
		}
	}
	if start < 0 {
		t.Fatalf("the page has no entry for %s, so this guard is measuring nothing", name)
	}

	var body []string
	for _, following := range lines[start+1:] {
		if strings.TrimSpace(following) == "" {
			break
		}
		body = append(body, following)
	}
	if len(body) == 0 {
		t.Fatalf("the entry for %s is empty, so this guard is measuring nothing", name)
	}
	return strings.Join(body, "\n")
}

// TestMainHelpDocumentsEverySubcommand checks that every command the binary accepts has
// both a synopsis line and an entry in the SUBCOMMANDS section.
//
// The list is written here rather than read from the source because the source expresses
// a subcommand as a string in a switch, which a scan cannot distinguish from any other
// string. The test therefore fails when a subcommand is added to this list without help,
// and the reviewer is the one who must add it: that is the point, because the reviewer is
// the only party who knows a new subcommand exists.
//
// Both halves are required, and the first version of this test checked only the synopsis.
// A mutation proved that insufficient: renaming the SUBCOMMANDS entry for "regenerate" to
// "regenerateX" left the test green, because the SYNOPSIS line still read
// "connector-node regenerate". A synopsis line tells a reader the command exists; only the
// entry tells them what it does, and the entry is what a reader scans the section for.
func TestMainHelpDocumentsEverySubcommand(t *testing.T) {
	text := Main("connector-node")
	entries := section(t, text, "SUBCOMMANDS")

	subcommands := []string{"run", "id", "regenerate", "credential", "scope", "help"}
	for _, name := range subcommands {
		if !strings.Contains(text, "connector-node "+name) {
			t.Errorf("Main help has no synopsis line for %q", name)
		}
		if !hasEntry(entries, name) {
			t.Errorf("Main help has no SUBCOMMANDS entry for %q", name)
		}
	}
}

// hasEntry reports whether a section documents a command as an entry rather than merely
// mentioning it in a sentence.
//
// An entry is a line indented by two spaces that begins with the command name, such as
// "  regenerate" or "  credential add [--key-id NAME]". A mention inside a paragraph is
// indented further, so the two-space prefix is what separates the entry from the prose.
func hasEntry(sectionText, name string) bool {
	for _, line := range strings.Split(sectionText, "\n") {
		if !strings.HasPrefix(line, "  "+name) {
			continue
		}
		rest := line[len("  "+name):]
		if rest == "" || rest[0] == ' ' {
			return true
		}
	}
	return false
}

// section returns the text of one upper-case section, from its heading to the next one.
//
// A missing section is a failure rather than an empty string, because a guard that
// silently measures nothing is the defect this file exists to prevent.
func section(t *testing.T, text, heading string) string {
	t.Helper()

	lines := strings.Split(text, "\n")
	start := -1
	for index, line := range lines {
		if line == heading {
			start = index
			break
		}
	}
	if start < 0 {
		t.Fatalf("the page has no %s section, so this guard is measuring nothing", heading)
	}

	var body []string
	for _, following := range lines[start+1:] {
		if following != "" && !strings.HasPrefix(following, " ") {
			break
		}
		body = append(body, following)
	}
	if len(body) == 0 {
		t.Fatalf("the %s section is empty, so this guard is measuring nothing", heading)
	}
	return strings.Join(body, "\n")
}

// TestCredentialHelpDocumentsEveryCredentialSubcommand checks that each credential
// operation has an entry in the SUBCOMMANDS section, not merely a mention elsewhere.
//
// The first version searched for the substring "credential list", which the EXAMPLES
// section satisfies on its own. A mutation proved it: renaming the SUBCOMMANDS entry for
// "list" to "listX" left the test green, because the example still read
// "connector-node credential list". An example shows the command being used; only the
// entry says what it does, and the entry is what a reader scans the section for.
func TestCredentialHelpDocumentsEveryCredentialSubcommand(t *testing.T) {
	text := Credential("connector-node")
	entries := section(t, text, "SUBCOMMANDS")

	for _, name := range []string{"add", "list", "remove"} {
		if !hasEntry(entries, name) {
			t.Errorf("Credential help has no SUBCOMMANDS entry for %q", name)
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
		"Scope":      Scope("connector-node"),
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
		"Scope":      Scope("connector-node"),
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
		"Scope":      Scope("connector-node"),
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
		"Scope":      Scope("connector-node"),
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
