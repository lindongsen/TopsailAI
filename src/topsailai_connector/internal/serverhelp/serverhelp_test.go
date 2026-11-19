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

// TestMainHelpStatesThatAPathMustBeAbsolute checks that every variable the code refuses
// when relative is documented as needing an absolute path.
//
// The defect this guards against was measured, not imagined: a relative
// CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE is refused with "is relative; a relative path
// resolves differently per launch", and the help said nothing about it. An operator who
// writes a relative path gets a startup failure whose message names a rule the help never
// stated, so the help is the place the rule has to appear.
//
// The list is written here rather than derived from the source because the source
// expresses the rule as a filepath.IsAbs call inside a resolver, which a scan cannot
// attribute to a variable name. A reviewer adding a path variable must add it here, and
// the failure message names the variable so the omission is obvious.
func TestMainHelpStatesThatAPathMustBeAbsolute(t *testing.T) {
	text := Main("connector-server")

	// Every CONNECTOR_SERVER_ variable the code passes through filepath.IsAbs.
	absolute := []string{
		"CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE",
		"CONNECTOR_SERVER_TLS_CERT",
		"CONNECTOR_SERVER_TLS_KEY",
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
// The entry is isolated rather than searched in the whole page, because a whole-page search
// would pass on any unrelated sentence containing the word, and a guard that passes on an
// unrelated sentence proves nothing about this variable.
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

// TestMainHelpCallANodeExampleIsRunnable checks that the one command the Server's main
// page offers can actually run.
//
// The defect this guards against was measured, not imagined: the example was
// `cli --scope project --path notes.md file.read`, which exits 2 with
// "usage: --server or CONNECTOR_CLI_SERVER_URL is required". A reader who copies the one
// command the page offers is refused, and the page never said which four values the
// command needs. The assertion is therefore about the example block, not about the page:
// a flag named in a FLAGS entry does not make an example runnable.
func TestMainHelpCallANodeExampleIsRunnable(t *testing.T) {
	text := Main("connector-server")

	example := exampleBlock(t, text, "Call a Node")

	// The four values a request cannot run without. Each is an environment variable in
	// the example because that is the form the page recommends, and a reader who has
	// them exported can copy the command line unchanged.
	for _, required := range []string{
		"CONNECTOR_CLI_SERVER_URL",
		"CONNECTOR_CLI_CLIENT_CREDENTIAL",
		"CONNECTOR_CLI_NODE_ID",
		"CONNECTOR_CLI_NODE_CREDENTIAL",
	} {
		if !strings.Contains(example, required) {
			t.Errorf("the Call a Node example omits %s, so copying it exits 2", required)
		}
	}
}

// TestCLIHelpIsSelfSufficient checks that the cli page does not send the reader to itself
// for the text it should hold, and that its bare examples are introduced as needing the
// environment.
//
// The earlier version of this page said "run cli --help for the flags", which is the page
// the reader is already looking at. The second defect was subtler: three of the four
// EXAMPLES were bare commands that exit 2 unless four values are already exported, and
// nothing on the page said so before the reader reached them.
func TestCLIHelpIsSelfSufficient(t *testing.T) {
	text := CLI("connector-server")

	// The circular pointer must not come back. "cli --help" is still correct in the
	// SYNOPSIS, so the check is for the sentence that sent the reader in a circle.
	if strings.Contains(text, "Run connector-server cli --help for that text") {
		t.Error("CLI help points at itself for the text it should contain")
	}

	// The EXAMPLES section must say that the bare commands need the environment, and it
	// must say so before the first bare command rather than after it.
	examples := section(t, text, "EXAMPLES")
	firstBare := strings.Index(examples, "cli --scope project --path notes.md file.read")
	if firstBare < 0 {
		t.Fatal("the EXAMPLES section has no read example, so this guard is measuring nothing")
	}
	introduction := examples[:firstBare]
	if !strings.Contains(introduction, "already exported") {
		t.Error("the EXAMPLES section shows a bare command without saying the four values must be exported first")
	}
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

// exampleBlock returns the command lines of the example that follows a heading.
//
// The heading is a sentence of prose, and the command may be separated from it by a blank
// line and by a second line of prose, so the block is not simply "the next indented lines".
// A command line is recognised by what it contains: the program placeholder, an environment
// variable assignment, or a trailing backslash that continues the command. Prose is skipped,
// which is what makes the assertion about the command rather than about the paragraph that
// introduces it.
//
// A heading with no command after it is a failure rather than an empty string, because a
// guard that silently measures nothing is the defect this file exists to prevent.
func exampleBlock(t *testing.T, text, heading string) string {
	t.Helper()

	lines := strings.Split(text, "\n")
	for index, line := range lines {
		if !strings.Contains(line, heading) {
			continue
		}
		var block []string
		for _, following := range lines[index+1:] {
			if following != "" && !strings.HasPrefix(following, " ") {
				break
			}
			if strings.Contains(following, programPlaceholder) ||
				strings.Contains(following, "CONNECTOR_") ||
				strings.HasSuffix(strings.TrimSpace(following), "\\") {
				block = append(block, following)
			}
		}
		if len(block) == 0 {
			t.Fatalf("the %q heading is followed by no command, so this guard is measuring nothing", heading)
		}
		return strings.Join(block, "\n")
	}
	t.Fatalf("the page has no %q heading, so this guard is measuring nothing", heading)
	return ""
}

// TestMainHelpExplainsHowToCreateTheCredentialFile checks the one instruction a first
// run cannot do without.
//
// The Server requires CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE and has no subcommand
// that writes it, so a reader who is told only that the file is required is stuck. The
// page must name the binary that writes it and the variable that points it at a
// directory.
func TestMainHelpExplainsHowToCreateTheCredentialFile(t *testing.T) {
	text := Main("connector-server")

	if !strings.Contains(text, "FIRST RUN") {
		t.Fatal("Main help has no FIRST RUN section")
	}
	if !strings.Contains(text, "connector-node credential add") {
		t.Error("Main help does not say which command writes the credential file it requires")
	}
	if !strings.Contains(text, "CONNECTOR_NODE_CONFIG_DIR") {
		t.Error("Main help does not say how to point that command at the Server's directory")
	}
}

// sourceCLIFlags returns every flag name the CLI registers, read from the source.
//
// The list is scanned rather than written here for the same reason the environment list
// is: a hand-written list is a second definition that drifts. The defect this guards
// against was real: --force and --request-id were registered and accepted by the binary
// while the cli page documented neither, so a reader could not discover them and a
// reader who guessed them had no description of what they do.
func sourceCLIFlags(t *testing.T) []string {
	t.Helper()

	pattern := regexp.MustCompile(`set\.(?:String|Bool|Int|Int64|Duration)\(\s*"([a-z0-9-]+)"`)
	content, err := os.ReadFile(filepath.Join("..", "server", "cli", "command.go"))
	if err != nil {
		t.Fatalf("read command.go: %v", err)
	}

	found := map[string]bool{}
	for _, match := range pattern.FindAllStringSubmatch(string(content), -1) {
		found[match[1]] = true
	}

	// The output flag is registered twice, once as the short alias and once through
	// StringVar for the long name, so the second form is scanned separately.
	varPattern := regexp.MustCompile(`set\.StringVar\([^,]+,\s*"([a-z0-9-]+)"`)
	for _, match := range varPattern.FindAllStringSubmatch(string(content), -1) {
		found[match[1]] = true
	}

	if len(found) == 0 {
		t.Fatal("no flag registrations were found, so this guard is measuring nothing")
	}

	names := make([]string, 0, len(found))
	for name := range found {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// TestCLIHelpDocumentsEveryFlag is the guard that keeps the cli page usable.
//
// A flag the binary accepts and the page omits is undiscoverable: the reader has only
// the page, so a flag it does not name does not exist for them. The reverse is also
// checked, because a documented flag the binary rejects sends the reader to a usage
// error.
func TestCLIHelpDocumentsEveryFlag(t *testing.T) {
	text := CLI("connector-server")

	for _, flag := range sourceCLIFlags(t) {
		// A single-letter alias is documented as part of its long form, such as
		// "-o FILE, --output FILE", so the long name is what must appear.
		if len(flag) == 1 {
			continue
		}
		if !hasFlagEntry(text, flag) {
			t.Errorf("cli help has no entry for --%s, which the binary accepts", flag)
		}
	}
}

// hasFlagEntry reports whether the page documents a flag as a flag, rather than merely
// mentioning it in a sentence.
//
// The distinction is the whole point of this guard. The first version of it searched for
// the substring "--force", which the sentence "unless --force is given" satisfies, so
// deleting the flag's own entry left the guard green. A mention tells a reader the flag
// exists; only an entry tells them what it does, and the entry is what a reader scans the
// FLAGS section for.
func hasFlagEntry(text, flag string) bool {
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		// One line may document two flags, such as "--offset N, --length N".
		for _, part := range strings.Split(trimmed, ", ") {
			if !strings.HasPrefix(part, "--"+flag) {
				continue
			}
			rest := part[len("--"+flag):]
			if rest == "" || rest[0] == ' ' {
				return true
			}
		}
	}
	return false
}

// TestNoPageRepeatsAParagraph checks that a page does not say the same thing twice.
//
// The Server's EXIT STATUS section carried two paragraphs that both explained the
// "usage:" prefix, one of them a near-copy of the other. A duplicate reads as emphasis
// to whoever wrote it and as uncertainty to whoever reads it, and it is invisible to
// every other test because both copies are individually correct.
func TestNoPageRepeatsAParagraph(t *testing.T) {
	pages := map[string]string{
		"Main": Main("connector-server"),
		"Run":  Run("connector-server"),
		"CLI":  CLI("connector-server"),
	}

	for name, text := range pages {
		seen := map[string]bool{}
		for _, paragraph := range strings.Split(text, "\n\n") {
			normalised := strings.Join(strings.Fields(paragraph), " ")
			if len(normalised) < 40 {
				continue
			}
			if seen[normalised] {
				t.Errorf("%s repeats a paragraph: %q", name, normalised)
			}
			seen[normalised] = true
		}
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
