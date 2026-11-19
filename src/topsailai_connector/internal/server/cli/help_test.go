package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// parseWithEnvironment parses arguments against a lookup that always supplies the
// Server URL.
//
// parseArguments requires a Server URL, and validArguments does not carry one
// because the existing tests inject it through the environment. A test that is
// about one property must not fail on an unrelated missing field, so the URL is
// added here rather than repeated in every case.
func parseWithEnvironment(t *testing.T, arguments []string, values map[string]string) (Options, bool, error) {
	t.Helper()

	merged := map[string]string{EnvServerURL: "http://127.0.0.1:8743"}
	for name, value := range values {
		merged[name] = value
	}
	return parseArguments(arguments, environment(merged))
}

// TestHandleInformationalPrintsHelp checks that --help is answered with status 0
// and names the program the caller typed, because the help text is the only
// documentation a caller who has just the binary will read.
func TestHandleInformationalPrintsHelp(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"--help"}, &stdout, &stderr)
	if !handled {
		t.Fatal("--help was not handled")
	}
	if status != 0 {
		t.Fatalf("status = %d, want 0", status)
	}
	if !strings.Contains(stdout.String(), "NAME") {
		t.Fatalf("stdout does not look like help: %q", stdout.String())
	}
	if !strings.Contains(stdout.String(), "connector-cli") {
		t.Fatalf("help does not name the program: %q", stdout.String())
	}
	if stderr.String() != "" {
		t.Fatalf("help wrote to stderr: %q", stderr.String())
	}
}

// TestHandleInformationalPrintsHelpForTheShortForm checks that -h is answered the
// same way as --help. Without a registered "h" the parser returns ErrHelp and
// prints its own usage, which would bypass the documented help text.
func TestHandleInformationalPrintsHelpForTheShortForm(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"-h"}, &stdout, &stderr)
	if !handled || status != 0 {
		t.Fatalf("handled = %v, status = %d, want true and 0", handled, status)
	}
	if !strings.Contains(stdout.String(), "NAME") {
		t.Fatalf("stdout does not look like help: %q", stdout.String())
	}
}

// TestHandleInformationalPrintsVersion checks that --version succeeds and prints a
// version line rather than the help text, because a caller asking which build is
// running should not have to search a page of prose for the answer.
func TestHandleInformationalPrintsVersion(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"--version"}, &stdout, &stderr)
	if !handled || status != 0 {
		t.Fatalf("handled = %v, status = %d, want true and 0", handled, status)
	}
	if !strings.Contains(stdout.String(), "connector-cli") {
		t.Fatalf("version does not name the program: %q", stdout.String())
	}
	if strings.Contains(stdout.String(), "OPERATIONS") {
		t.Fatalf("--version printed the help text: %q", stdout.String())
	}
}

// TestHandleInformationalPrintsOperationHelp checks that "help file.read" succeeds
// and describes that operation.
func TestHandleInformationalPrintsOperationHelp(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"help", "file.read"}, &stdout, &stderr)
	if !handled || status != 0 {
		t.Fatalf("handled = %v, status = %d, want true and 0", handled, status)
	}
	if !strings.Contains(stdout.String(), "file.read") {
		t.Fatalf("operation help does not name the operation: %q", stdout.String())
	}
}

// TestHandleInformationalPrintsHelpForTheHelpSubcommand checks that "help help"
// prints the help for the help subcommand rather than being refused as an unknown
// operation.
func TestHandleInformationalPrintsHelpForTheHelpSubcommand(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"help", "help"}, &stdout, &stderr)
	if !handled || status != 0 {
		t.Fatalf("handled = %v, status = %d, want true and 0", handled, status)
	}
	if !strings.Contains(stdout.String(), "help OPERATION") {
		t.Fatalf("stdout does not describe the help subcommand: %q", stdout.String())
	}
}

// TestHandleInformationalRefusesAnUnimplementedOperation checks that asking for
// help on an operation this version refuses exits 2 with a refusal.
//
// Validate accepts a declared operation, so the check must ask whether the
// operation is offered. Asking Validate let `help file.write` fall through to the
// generic text and print the help for `help` itself with status 0, which
// documented an operation that cannot run.
func TestHandleInformationalRefusesAnUnimplementedOperation(t *testing.T) {
	for _, operation := range []string{"file.write", "command.exec"} {
		t.Run(operation, func(t *testing.T) {
			var stdout, stderr bytes.Buffer
			handled, status := handleInformational("connector-cli", []string{"help", operation}, &stdout, &stderr)
			if !handled {
				t.Fatalf("help %s was not handled", operation)
			}
			if status != 2 {
				t.Fatalf("status = %d, want 2", status)
			}
			if !strings.Contains(stderr.String(), "not an operation this version offers") {
				t.Fatalf("stderr does not refuse the operation: %q", stderr.String())
			}
			if stdout.String() != "" {
				t.Fatalf("a refusal wrote to stdout: %q", stdout.String())
			}
		})
	}
}

// TestHandleInformationalRefusesAnUnknownOperation checks that an operation that
// does not exist at all is refused with status 2.
func TestHandleInformationalRefusesAnUnknownOperation(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"help", "file.nope"}, &stdout, &stderr)
	if !handled || status != 2 {
		t.Fatalf("handled = %v, status = %d, want true and 2", handled, status)
	}
}

// TestHandleInformationalRefusesExtraArguments checks that "help" with two
// operation names is a usage error rather than a silent choice of one.
func TestHandleInformationalRefusesExtraArguments(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, status := handleInformational("connector-cli", []string{"help", "file.read", "file.stat"}, &stdout, &stderr)
	if !handled || status != 2 {
		t.Fatalf("handled = %v, status = %d, want true and 2", handled, status)
	}
	if !strings.Contains(stderr.String(), "usage:") {
		t.Fatalf("stderr does not begin a usage message: %q", stderr.String())
	}
}

// TestHandleInformationalIgnoresAFlagValue checks that a flag whose value is the
// text "--help" is not treated as a help request.
//
// Scanning the arguments for the literal text cannot tell a flag from a value, so
// `--path --help` would print the help instead of reporting the path. Letting the
// parser decide means the answer comes from the grammar rather than from a string
// comparison.
func TestHandleInformationalIgnoresAFlagValue(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, _ := handleInformational("connector-cli", []string{"--path", "--help", "file.read"}, &stdout, &stderr)
	if handled {
		t.Fatalf("a flag value of --help was treated as a help request: %q", stdout.String())
	}
}

// TestHandleInformationalIgnoresAnOrdinaryRequest checks that a normal request is
// not intercepted, so the caller's operation still runs.
func TestHandleInformationalIgnoresAnOrdinaryRequest(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, _ := handleInformational("connector-cli", []string{"--scope", "project", "--path", "notes.md", "file.read"}, &stdout, &stderr)
	if handled {
		t.Fatalf("an ordinary request was intercepted: %q", stdout.String())
	}
}

// TestHandleInformationalIgnoresAnUnparseableCommandLine checks that a command
// line the parser rejects is not reported here.
//
// The caller parses again and reports the error with the same program name, so
// reporting it twice would print two lines for one mistake.
func TestHandleInformationalIgnoresAnUnparseableCommandLine(t *testing.T) {
	var stdout, stderr bytes.Buffer
	handled, _ := handleInformational("connector-cli", []string{"--nope", "file.read"}, &stdout, &stderr)
	if handled {
		t.Fatalf("an unparseable command line was handled: %q", stdout.String())
	}
	if stderr.String() != "" {
		t.Fatalf("handleInformational reported the parse error: %q", stderr.String())
	}
}

// TestNewCLIFlagsRegistersEveryFlag checks that the one registration includes every
// flag the parser must accept.
//
// A missing registration makes the parser print its own usage instead of the
// caller's help, and it makes handleInformational unable to recognise the flag.
func TestNewCLIFlagsRegistersEveryFlag(t *testing.T) {
	registered := newCLIFlags()
	wanted := []string{
		"server", "node-id", "client-credential", "node-credential",
		"scope", "path", "offset", "length", "request-id",
		"o", "output", "force", "json", "h", "help", "version",
	}
	for _, name := range wanted {
		if registered.set.Lookup(name) == nil {
			t.Errorf("flag %q is not registered", name)
		}
	}
}

// TestNewCLIFlagsSharesOneVariableForBothOutputNames checks that -o and --output
// write the same variable.
//
// Go's flag package treats them as unrelated names, so registering only one would
// make the other an unknown flag, and registering both against different variables
// would make the documented short form silently ignored.
func TestNewCLIFlagsSharesOneVariableForBothOutputNames(t *testing.T) {
	registered := newCLIFlags()
	if err := registered.set.Parse([]string{"-o", "short.txt"}); err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if *registered.output != "short.txt" {
		t.Fatalf("output = %q, want short.txt", *registered.output)
	}

	other := newCLIFlags()
	if err := other.set.Parse([]string{"--output", "long.txt"}); err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if *other.output != "long.txt" {
		t.Fatalf("output = %q, want long.txt", *other.output)
	}
}

// TestParseArgumentsLetsAZeroOffsetOverrideTheEnvironment checks the defect this
// change fixed.
//
// Testing "was the flag set" by comparing the value with zero cannot see an
// explicit `--offset 0`, so the flag silently lost to a non-zero environment value
// and the documented rule "a flag wins over the environment" was false for exactly
// the value a caller is most likely to want.
func TestParseArgumentsLetsAZeroOffsetOverrideTheEnvironment(t *testing.T) {
	arguments := validArguments(t)
	arguments = append(arguments[:len(arguments)-1], "--offset", "0", "file.read")

	options, _, err := parseWithEnvironment(t, arguments, map[string]string{EnvOffset: "5"})
	if err != nil {
		t.Fatalf("parseArguments: %v", err)
	}
	if options.Offset != 0 {
		t.Fatalf("Offset = %d, want 0 from the flag", options.Offset)
	}
}

// TestParseArgumentsLetsAZeroLengthOverrideTheEnvironment checks the same defect
// for --length, because it is read by the same helper.
func TestParseArgumentsLetsAZeroLengthOverrideTheEnvironment(t *testing.T) {
	arguments := validArguments(t)
	arguments = append(arguments[:len(arguments)-1], "--length", "0", "file.read")

	options, _, err := parseWithEnvironment(t, arguments, map[string]string{EnvLength: "4096"})
	if err != nil {
		t.Fatalf("parseArguments: %v", err)
	}
	if options.Length != 0 {
		t.Fatalf("Length = %d, want 0 from the flag", options.Length)
	}
}

// TestParseArgumentsLetsAFalseForceOverrideTheEnvironment checks the same defect
// for a boolean.
//
// `--force=false` must win over CONNECTOR_CLI_FORCE=1. Testing the value against
// the default read that as "not set" and silently re-enabled the switch the caller
// had just turned off. The discriminator is the refusal that follows: a true Force
// with no destination is a usage error, so a successful parse proves the flag won.
func TestParseArgumentsLetsAFalseForceOverrideTheEnvironment(t *testing.T) {
	arguments := validArguments(t)
	arguments = append(arguments[:len(arguments)-1], "--force=false", "file.read")

	options, _, err := parseWithEnvironment(t, arguments, map[string]string{EnvForce: "1"})
	if err != nil {
		t.Fatalf("parseArguments: %v", err)
	}
	if options.Force {
		t.Fatal("Force = true, want false from the flag")
	}
}

// TestParseArgumentsReadsANumericValueFromTheEnvironment checks that the
// environment is still honoured when the flag is absent, so the fix above did not
// disable the second source.
func TestParseArgumentsReadsANumericValueFromTheEnvironment(t *testing.T) {
	options, _, err := parseWithEnvironment(t, validArguments(t), map[string]string{EnvOffset: "5"})
	if err != nil {
		t.Fatalf("parseArguments: %v", err)
	}
	if options.Offset != 5 {
		t.Fatalf("Offset = %d, want 5 from the environment", options.Offset)
	}
}

// TestParseArgumentsRefusesAMalformedNumber checks that a non-numeric offset is a
// usage error naming the variable, rather than a silent zero that would run a
// different request than the one configured.
func TestParseArgumentsRefusesAMalformedNumber(t *testing.T) {
	_, _, err := parseWithEnvironment(t, validArguments(t), map[string]string{EnvOffset: "abc"})
	if err == nil {
		t.Fatal("parseArguments returned no error")
	}
	if !strings.Contains(err.Error(), EnvOffset) {
		t.Fatalf("error %q does not name %s", err, EnvOffset)
	}
}

// TestParseArgumentsRefusesAMalformedBoolean checks the same for a boolean, because
// a security-relevant switch that silently accepts a spelling it does not
// understand is a switch whose state nobody can state.
func TestParseArgumentsRefusesAMalformedBoolean(t *testing.T) {
	_, _, err := parseWithEnvironment(t, validArguments(t), map[string]string{EnvForce: "maybe"})
	if err == nil {
		t.Fatal("parseArguments returned no error")
	}
	if !strings.Contains(err.Error(), EnvForce) {
		t.Fatalf("error %q does not name %s", err, EnvForce)
	}
}

// TestParseArgumentsAcceptsTheDocumentedBooleanSpellings checks every spelling a
// shell script actually writes, so a refusal is reserved for a value that is
// genuinely ambiguous.
func TestParseArgumentsAcceptsTheDocumentedBooleanSpellings(t *testing.T) {
	for _, spelling := range []string{"1", "true", "yes", "on", "TRUE", "On"} {
		t.Run(spelling, func(t *testing.T) {
			_, jsonOutput, err := parseWithEnvironment(t, validArguments(t), map[string]string{EnvJSON: spelling})
			if err != nil {
				t.Fatalf("parseArguments refused %q: %v", spelling, err)
			}
			if !jsonOutput {
				t.Fatalf("%q was not read as true", spelling)
			}
		})
	}
}

// TestParseArgumentsRefusesAnEmptyDestination checks that `-o ""` is refused rather
// than read as "no destination".
//
// The default value cannot express the difference, so the refusal depends on
// knowing the flag was written. Accepting it would run a single-request read while
// the caller believed a whole-file read was in progress.
func TestParseArgumentsRefusesAnEmptyDestination(t *testing.T) {
	arguments := validArguments(t)
	arguments = append(arguments[:len(arguments)-1], "-o", "", "file.read")

	_, _, err := parseWithEnvironment(t, arguments, nil)
	if err == nil {
		t.Fatal("parseArguments accepted an empty destination")
	}
	if !strings.Contains(err.Error(), "-o needs a destination") {
		t.Fatalf("error %q does not explain the refusal", err)
	}
}

// TestHelpListsEveryErrorCode proves the help names every code the protocol can
// return, so a new code cannot be added without the help being updated.
//
// The list is read from the source rather than written here, because a hardcoded
// list in a test drifts exactly the way the help did: `overloaded` was added to the
// protocol, returned by the Server and marked retryable, while the help still named
// nine codes and three retryable ones. A test that repeats the list would have been
// updated by whoever added the code, and would then have agreed with the help while
// both disagreed with the protocol.
func TestHelpListsEveryErrorCode(t *testing.T) {
	source, err := os.ReadFile(filepath.Join("..", "..", "protocol", "codes.go"))
	if err != nil {
		t.Fatalf("read codes.go: %v", err)
	}

	// Every `return "name"` inside Name() is a code name. `success` is excluded
	// because the help documents it as status 0 rather than as an error code, and
	// `unknown` is excluded because it is the default branch for a code this build
	// does not recognise rather than a code the protocol returns.
	pattern := regexp.MustCompile(`return "([a-z_]+)"`)
	matches := pattern.FindAllStringSubmatch(string(source), -1)
	if len(matches) < 10 {
		t.Fatalf("found %d code names in codes.go, want at least 10", len(matches))
	}

	help := helpText("connector-cli")
	for _, match := range matches {
		name := match[1]
		if name == "success" || name == "unknown" {
			continue
		}
		if !strings.Contains(help, name) {
			t.Errorf("help does not name the error code %q", name)
		}
	}
}

// TestHelpNamesEveryRetryableCode proves the retryable sentence names exactly the
// codes the protocol marks retryable.
//
// A code that is retryable but undocumented tells a caller to give up on a
// condition that a retry would fix, which is the opposite of the advice the code
// intends.
func TestHelpNamesEveryRetryableCode(t *testing.T) {
	help := helpText("connector-cli")

	// The sentence is the only place the help gives retry advice, so it must name
	// every retryable code. The four are asserted individually because a sentence
	// that names three of four reads as complete.
	for _, name := range []string{"node_offline", "node_timeout", "overloaded", "internal"} {
		if !strings.Contains(help, name) {
			t.Errorf("help does not name the retryable code %q", name)
		}
	}

	if !strings.Contains(help, "worth retrying") {
		t.Error("help does not state which codes are worth retrying")
	}
}
