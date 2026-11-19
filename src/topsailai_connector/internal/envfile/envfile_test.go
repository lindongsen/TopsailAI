package envfile

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestParseReadsPairs checks the ordinary shape: one KEY=VALUE per line.
func TestParseReadsPairs(t *testing.T) {
	values, err := Parse([]byte("A=1\nB=two\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "1" || values["B"] != "two" {
		t.Fatalf("got %#v, want A=1 B=two", values)
	}
}

// TestParseSkipsCommentsAndBlankLines checks that a comment and an empty line
// contribute nothing, so a documented file parses to the same map as a bare one.
func TestParseSkipsCommentsAndBlankLines(t *testing.T) {
	content := "# a comment\n\n   \nA=1\n  # indented comment\n"
	values, err := Parse([]byte(content))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if len(values) != 1 || values["A"] != "1" {
		t.Fatalf("got %#v, want only A=1", values)
	}
}

// TestParseAcceptsExportPrefix checks that a line copied out of a shell script
// parses, because that is how a caller writes one.
func TestParseAcceptsExportPrefix(t *testing.T) {
	values, err := Parse([]byte("export A=1\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "1" {
		t.Fatalf("got %#v, want A=1", values)
	}
}

// TestParseRemovesOneMatchingQuotePair checks both quote styles, and checks that
// the quotes are removed rather than kept as part of the value.
func TestParseRemovesOneMatchingQuotePair(t *testing.T) {
	values, err := Parse([]byte("A=\"x y\"\nB='z'\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "x y" {
		t.Fatalf("A = %q, want %q", values["A"], "x y")
	}
	if values["B"] != "z" {
		t.Fatalf("B = %q, want %q", values["B"], "z")
	}
}

// TestParseKeepsUnmatchedQuote checks that a value with only one quote keeps it.
// Removing it would produce a half-quoted credential, which authenticates nothing
// and is harder to diagnose than a value that visibly contains a quote.
func TestParseKeepsUnmatchedQuote(t *testing.T) {
	values, err := Parse([]byte("A=\"x\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "\"x" {
		t.Fatalf("A = %q, want %q", values["A"], "\"x")
	}
}

// TestParseDoesNotExpandVariables checks that a value is exactly the bytes after
// the equals sign. Expansion would rewrite a credential containing a dollar sign.
func TestParseDoesNotExpandVariables(t *testing.T) {
	values, err := Parse([]byte("A=$HOME\nB=${HOME}\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "$HOME" || values["B"] != "${HOME}" {
		t.Fatalf("got %#v, want the literal text", values)
	}
}

// TestParseKeepsLastDuplicate checks that a repeated key keeps its last value,
// which is what a shell does and what makes an appended override work.
func TestParseKeepsLastDuplicate(t *testing.T) {
	values, err := Parse([]byte("A=1\nA=2\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "2" {
		t.Fatalf("A = %q, want 2", values["A"])
	}
}

// TestParseKeepsEmptyValue checks that KEY= defines an empty value rather than
// being refused. The caller layer treats an empty value as unset, so the parser
// must not decide that question.
func TestParseKeepsEmptyValue(t *testing.T) {
	values, err := Parse([]byte("A=\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if value, ok := values["A"]; !ok || value != "" {
		t.Fatalf("got %#v, want A present and empty", values)
	}
}

// TestParseRefusesMalformedLines checks every shape that is not KEY=VALUE. Each
// one is refused rather than skipped, because a configuration that is half-read
// is one nobody can reason about.
func TestParseRefusesMalformedLines(t *testing.T) {
	cases := map[string]string{
		"no equals sign":  "A\n",
		"empty key":       "=1\n",
		"space in key":    "A B=1\n",
		"dash in key":     "A-B=1\n",
		"dot in key":      "A.B=1\n",
		"control in key":  "A\tB=1\n",
		"only export":     "export\n",
		"export no value": "export A\n",
	}
	for name, content := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Parse([]byte(content)); err == nil {
				t.Fatalf("Parse(%q) returned no error", content)
			}
		})
	}
}

// TestParseReportsTheLineNumber checks that the error names the line, because a
// file with forty lines and one mistake is otherwise a search.
func TestParseReportsTheLineNumber(t *testing.T) {
	_, err := Parse([]byte("A=1\nB=2\nbroken\n"))
	if err == nil {
		t.Fatal("Parse returned no error")
	}
	if !strings.Contains(err.Error(), "line 3") {
		t.Fatalf("error %q does not name line 3", err)
	}
}

// TestParseAcceptsAValueContainingEquals checks that only the first equals sign
// splits, so a value that is itself a query string survives.
func TestParseAcceptsAValueContainingEquals(t *testing.T) {
	values, err := Parse([]byte("A=b=c\n"))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if values["A"] != "b=c" {
		t.Fatalf("A = %q, want %q", values["A"], "b=c")
	}
}

// TestLoadReturnsEmptyMapForAMissingFile checks that an absent file is not an
// error. The file is a convenience, so its absence must not stop the program.
func TestLoadReturnsEmptyMapForAMissingFile(t *testing.T) {
	values, err := Load(filepath.Join(t.TempDir(), "absent"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(values) != 0 {
		t.Fatalf("got %#v, want an empty map", values)
	}
}

// TestLoadReadsAFile checks the ordinary case through the filesystem.
func TestLoadReadsAFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("A=1\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	values, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if values["A"] != "1" {
		t.Fatalf("got %#v, want A=1", values)
	}
}

// TestLoadNamesTheFileInTheError checks that a malformed file reports its path,
// because the caller may have several configuration files.
func TestLoadNamesTheFileInTheError(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("broken\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	_, err := Load(path)
	if err == nil {
		t.Fatal("Load returned no error")
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("error %q does not name %q", err, path)
	}
}

// TestLoadRefusesADirectory checks that a path naming a directory is an error
// rather than an empty configuration, because the caller believes a file is in
// force.
func TestLoadRefusesADirectory(t *testing.T) {
	if _, err := Load(t.TempDir()); err == nil {
		t.Fatal("Load returned no error for a directory")
	}
}
