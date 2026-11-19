package helpdispatch

import (
	"errors"
	"strings"
	"testing"
)

// testCatalog is a small catalog with the shapes the real ones have: a main page, a
// version line, a page for a command, a page for a two-word command, and a value flag.
func testCatalog() Catalog {
	return Catalog{
		Main:    "MAIN PAGE",
		Version: "prog 1.0\n",
		Pages: map[string]string{
			"run":            "RUN PAGE",
			"credential":     "CREDENTIAL PAGE",
			"credential add": "CREDENTIAL ADD PAGE",
		},
		Commands:   []string{"run", "credential"},
		ValueFlags: []string{"--key-id"},
	}
}

// TestResolveAnswersHelpWithStatusZero checks the ordinary case.
func TestResolveAnswersHelpWithStatusZero(t *testing.T) {
	for _, arguments := range [][]string{{"--help"}, {"-h"}} {
		result := Resolve("prog", arguments, testCatalog())
		if !result.Handled {
			t.Fatalf("Resolve(%v) was not handled", arguments)
		}
		if result.Status != 0 {
			t.Errorf("Resolve(%v) status = %d, want 0: a help request succeeded", arguments, result.Status)
		}
		if result.Stdout != "MAIN PAGE" {
			t.Errorf("Resolve(%v) stdout = %q, want the main page", arguments, result.Stdout)
		}
		if result.Stderr != "" {
			t.Errorf("Resolve(%v) stderr = %q, want nothing: help is not an error", arguments, result.Stderr)
		}
	}
}

// TestResolveAnswersVersion checks that --version prints the version line.
func TestResolveAnswersVersion(t *testing.T) {
	result := Resolve("prog", []string{"--version"}, testCatalog())
	if !result.Handled || result.Status != 0 {
		t.Fatalf("Resolve(--version) = %+v, want handled with status 0", result)
	}
	if result.Stdout != "prog 1.0\n" {
		t.Errorf("stdout = %q, want the version line", result.Stdout)
	}
}

// TestResolvePrefersTheFlagOverTheSubcommand checks the order of explicitness.
//
// `--help help` must print the main page, because the flag is the more explicit form. The
// reverse order would make the flag's meaning depend on a word that follows it.
func TestResolvePrefersTheFlagOverTheSubcommand(t *testing.T) {
	result := Resolve("prog", []string{"--help", "help"}, testCatalog())
	if result.Stdout != "MAIN PAGE" {
		t.Errorf("stdout = %q, want the main page", result.Stdout)
	}
}

// TestResolvePrintsThePageForTheNamedSubcommand checks the `help NAME` form.
func TestResolvePrintsThePageForTheNamedSubcommand(t *testing.T) {
	result := Resolve("prog", []string{"help", "run"}, testCatalog())
	if !result.Handled || result.Status != 0 {
		t.Fatalf("Resolve(help run) = %+v, want handled with status 0", result)
	}
	if result.Stdout != "RUN PAGE" {
		t.Errorf("stdout = %q, want the run page", result.Stdout)
	}
}

// TestResolveRefusesAnUnknownNameWithStatusTwo checks that a name the binary does not
// offer is a usage error rather than a success.
//
// Status 0 would tell a caller the name was valid, and the caller would then use it.
func TestResolveRefusesAnUnknownNameWithStatusTwo(t *testing.T) {
	result := Resolve("prog", []string{"help", "nosuch"}, testCatalog())
	if !result.Handled {
		t.Fatal("Resolve(help nosuch) was not handled")
	}
	if result.Status != 2 {
		t.Errorf("status = %d, want 2", result.Status)
	}
	if !strings.HasPrefix(result.Stderr, "prog: usage: ") {
		t.Errorf("stderr = %q, want a usage: message", result.Stderr)
	}
	if !strings.Contains(result.Stderr, "nosuch") {
		t.Errorf("stderr = %q, want the rejected name", result.Stderr)
	}
	if result.Stdout != "" {
		t.Errorf("stdout = %q, want nothing: the request was refused", result.Stdout)
	}
}

// TestResolveRefusesTooManyWords checks that `help a b` is a usage error.
func TestResolveRefusesTooManyWords(t *testing.T) {
	result := Resolve("prog", []string{"help", "a", "b"}, testCatalog())
	if result.Status != 2 {
		t.Errorf("status = %d, want 2", result.Status)
	}
	if !strings.Contains(result.Stderr, "usage:") {
		t.Errorf("stderr = %q, want a usage: message", result.Stderr)
	}
}

// TestResolvePrintsTheMostSpecificPage checks the longest-match rule.
//
// `credential add --help` must print the page for `credential add`, not the page for
// `credential`. The shorter page is a summary, and a reader who asked about one
// subcommand would be answered with a document about three.
func TestResolvePrintsTheMostSpecificPage(t *testing.T) {
	result := Resolve("prog", []string{"credential", "add", "--help"}, testCatalog())
	if result.Stdout != "CREDENTIAL ADD PAGE" {
		t.Errorf("stdout = %q, want the credential add page", result.Stdout)
	}
}

// TestResolveFallsBackToTheParentPage checks the shorter form still works.
func TestResolveFallsBackToTheParentPage(t *testing.T) {
	result := Resolve("prog", []string{"credential", "--help"}, testCatalog())
	if result.Stdout != "CREDENTIAL PAGE" {
		t.Errorf("stdout = %q, want the credential page", result.Stdout)
	}
}

// TestResolveTreatsAValueFlagValueAsAValue is the regression test for the defect the CLI
// already recorded.
//
// `credential add --key-id --help` names a key id whose value happens to be `--help`. A
// scan of the argument text cannot tell a flag from a value, so without the value-flag
// rule this command would print help instead of creating a credential named `--help`.
func TestResolveTreatsAValueFlagValueAsAValue(t *testing.T) {
	result := Resolve("prog", []string{"credential", "add", "--key-id", "--help"}, testCatalog())
	if result.Handled {
		t.Fatalf("Resolve treated the value of --key-id as a help request: %+v", result)
	}
}

// TestResolveIgnoresAHelpTokenAfterAValueFlag checks the same rule for --version.
func TestResolveIgnoresAHelpTokenAfterAValueFlag(t *testing.T) {
	result := Resolve("prog", []string{"credential", "add", "--key-id", "--version"}, testCatalog())
	if result.Handled {
		t.Fatalf("Resolve treated the value of --key-id as a version request: %+v", result)
	}
}

// TestResolveStillAnswersHelpAfterAValueFlagPair checks that the rule does not swallow a
// later help request.
//
// The value is consumed, so the token after it is a flag again. A rule that skipped every
// token after a value flag would make `--key-id x --help` silently ignore the help.
func TestResolveStillAnswersHelpAfterAValueFlagPair(t *testing.T) {
	result := Resolve("prog", []string{"credential", "add", "--key-id", "x", "--help"}, testCatalog())
	if !result.Handled {
		t.Fatal("Resolve ignored a help request that followed a value flag pair")
	}
	if result.Stdout != "CREDENTIAL ADD PAGE" {
		t.Errorf("stdout = %q, want the credential add page", result.Stdout)
	}
}

// TestResolveReportsNoRequestForAnOrdinaryCommandLine checks that a normal command is not
// intercepted.
func TestResolveReportsNoRequestForAnOrdinaryCommandLine(t *testing.T) {
	commandLines := [][]string{
		{},
		{"run"},
		{"id"},
		{"credential", "add", "--key-id", "name"},
		{"run", "--listen", ":8443"},
	}
	for _, arguments := range commandLines {
		if result := Resolve("prog", arguments, testCatalog()); result.Handled {
			t.Errorf("Resolve(%v) was handled, want the caller to run the subcommand", arguments)
		}
	}
}

// TestResolveAnswersBareHelpSubcommandWithTheMainPage checks `help` alone.
func TestResolveAnswersBareHelpSubcommandWithTheMainPage(t *testing.T) {
	result := Resolve("prog", []string{"help"}, testCatalog())
	if !result.Handled || result.Status != 0 {
		t.Fatalf("Resolve(help) = %+v, want handled with status 0", result)
	}
	if result.Stdout != "MAIN PAGE" {
		t.Errorf("stdout = %q, want the main page", result.Stdout)
	}
}

// TestResolveAnswersHelpHelpWithTheMainPage checks the self-referential form.
func TestResolveAnswersHelpHelpWithTheMainPage(t *testing.T) {
	result := Resolve("prog", []string{"help", "help"}, testCatalog())
	if result.Stdout != "MAIN PAGE" {
		t.Errorf("stdout = %q, want the main page", result.Stdout)
	}
}

// TestUsageErrorCarriesThePrefix checks that the message and the status agree.
//
// The prefix is added by the type rather than at each call site, so a caller cannot
// produce a usage error whose message does not begin with "usage:".
func TestUsageErrorCarriesThePrefix(t *testing.T) {
	err := Usagef("bad %s", "thing")
	if !strings.HasPrefix(err.Error(), "usage: ") {
		t.Errorf("Error() = %q, want a usage: prefix", err.Error())
	}
	if !strings.Contains(err.Error(), "bad thing") {
		t.Errorf("Error() = %q, want the formatted message", err.Error())
	}
}

// TestIsUsageRecognisesAWrappedUsageError checks that adding context does not change the
// status.
//
// A caller that wraps a usage error to add a path or a name must not thereby turn status
// 2 into 1, because the message still begins with "usage:".
func TestIsUsageRecognisesAWrappedUsageError(t *testing.T) {
	wrapped := &wrappedError{inner: Usagef("bad")}
	if !IsUsage(wrapped) {
		t.Error("IsUsage did not recognise a wrapped usage error")
	}
}

// TestIsUsageRejectsAnOrdinaryError checks the negative case.
func TestIsUsageRejectsAnOrdinaryError(t *testing.T) {
	if IsUsage(&wrappedError{inner: errOrdinary}) {
		t.Error("IsUsage accepted an ordinary error")
	}
	if IsUsage(nil) {
		t.Error("IsUsage(nil) = true, want false")
	}
}

// wrappedError is an error that wraps another, used to prove IsUsage unwraps.
type wrappedError struct {
	inner error
}

func (e *wrappedError) Error() string { return "context: " + e.inner.Error() }
func (e *wrappedError) Unwrap() error { return e.inner }

// errOrdinary is a plain error for the negative case.
var errOrdinary = errors.New("ordinary failure")
