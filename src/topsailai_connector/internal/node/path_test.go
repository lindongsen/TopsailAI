package node

import (
	"strings"
	"testing"
)

// TestValidateRelativePathAccepts checks the paths a caller may legitimately
// send. The list is deliberately boring: an ordinary name, a nested name and a
// name with spaces inside a component, because a space is only dangerous at the
// edges where Windows strips it.
func TestValidateRelativePathAccepts(t *testing.T) {
	accepted := []string{
		"a.txt",
		"sub/nested.txt",
		"a/b/c/d.txt",
		"name with spaces.txt",
		"dotted.name.with.dots",
		"UPPER.TXT",
		"unicode-\u00e9\u00e8.txt",
		"a-b_c.d",
		"..hidden",
		"...three",
		"a..b",
	}

	for _, path := range accepted {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err != nil {
				t.Fatalf("ValidateRelativePath(%q) = %v, want nil", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsTraversal checks that every form of parent
// traversal is refused by the grammar.
//
// The refusal must happen before the filesystem is touched, because os.Root
// reports `a/../../outside/secret.txt` as a missing file rather than as an
// escape. If the grammar let it through, the caller would see not_found and
// learn that the path was never resolved.
func TestValidateRelativePathRejectsTraversal(t *testing.T) {
	rejected := []string{
		"..",
		"../",
		"../outside/secret.txt",
		"a/../b",
		"a/..",
		"a/b/../../c",
		"sub/../../../etc/passwd",
	}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "traversal") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a traversal refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsAbsolute checks that an absolute path is
// refused on the raw first byte rather than through filepath.IsAbs, because
// filepath.IsAbs answers for the host platform only: on Linux it accepts
// `C:\Windows` as a relative path.
func TestValidateRelativePathRejectsAbsolute(t *testing.T) {
	rejected := []string{
		"/etc/passwd",
		"/",
		"//server/share/file",
		`\windows\system32`,
		`\`,
	}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "absolute") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want an absolute-path refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsDotComponent checks that a `.` component is
// refused rather than normalised. Normalising would mean the checked name and
// the opened name are produced by two different pieces of code, and the
// difference between them is where a fence bug lives.
func TestValidateRelativePathRejectsDotComponent(t *testing.T) {
	rejected := []string{".", "./a", "a/.", "a/./b"}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
		})
	}
}

// TestValidateRelativePathRejectsEmptyComponent checks that a doubled separator
// is a rejection instead of a second spelling of the same name. A deny list
// compared against one spelling would be bypassed by the other.
func TestValidateRelativePathRejectsEmptyComponent(t *testing.T) {
	rejected := []string{"a//b", "a/", "a//", "//a"}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
		})
	}
}

// TestValidateRelativePathRejectsNUL checks that a NUL byte is refused, because
// a NUL truncates the name at the syscall boundary: the checked name and the
// opened name would differ.
func TestValidateRelativePathRejectsNUL(t *testing.T) {
	for _, path := range []string{"a\x00b", "a\x00", "\x00a"} {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "NUL") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a NUL refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsBackslash checks that a backslash is refused
// on every platform. On Windows it is a separator, so accepting it would make
// one request mean two different paths depending on the host.
func TestValidateRelativePathRejectsBackslash(t *testing.T) {
	for _, path := range []string{`a\b`, `sub\nested.txt`, `a\`} {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "backslash") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a backslash refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsColon checks that a colon is refused, because
// on Windows it introduces a drive letter or an alternate data stream.
func TestValidateRelativePathRejectsColon(t *testing.T) {
	for _, path := range []string{"a:b", "C:x", "file.txt:stream", "a/b:c"} {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "colon") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a colon refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsControlCharacters checks that control
// characters are refused. A newline in a name is how a log line gets forged and
// how a terminal gets driven.
func TestValidateRelativePathRejectsControlCharacters(t *testing.T) {
	rejected := []string{"a\tb", "a\nb", "a\rb", "a\x1bb", "a\x7fb", "a\x01b"}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "control character") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a control-character refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsTrailingDotOrSpace checks that a component
// ending in a dot or a space is refused. Windows strips both, so the checked
// name and the opened name would differ.
func TestValidateRelativePathRejectsTrailingDotOrSpace(t *testing.T) {
	rejected := []string{"a.", "a ", "a./b", "a /b", "sub/a."}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
		})
	}
}

// TestValidateRelativePathRejectsLeadingSpace checks that a component starting
// with a space is refused, because a name that differs from what a policy
// author sees is a name they cannot reason about.
func TestValidateRelativePathRejectsLeadingSpace(t *testing.T) {
	for _, path := range []string{" a", "sub/ a", "  a"} {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
		})
	}
}

// TestValidateRelativePathRejectsReservedDeviceNames checks that the Windows
// device names are refused on every platform, with any case and with any
// extension, because `NUL`, `nul` and `NUL.txt` are the same device.
func TestValidateRelativePathRejectsReservedDeviceNames(t *testing.T) {
	rejected := []string{
		"CON", "con", "Con",
		"PRN", "AUX", "NUL", "nul",
		"NUL.txt", "con.log", "aux.tar.gz",
		"COM1", "com9", "LPT1", "lpt9",
		"sub/CON", "sub/nul.txt",
	}

	for _, path := range rejected {
		t.Run(path, func(t *testing.T) {
			err := ValidateRelativePath(path, false)
			if err == nil {
				t.Fatalf("ValidateRelativePath(%q) = nil, want a refusal", path)
			}
			if !strings.Contains(err.Error(), "reserved device name") {
				t.Fatalf("ValidateRelativePath(%q) = %v, want a reserved-device refusal", path, err)
			}
		})
	}
}

// TestValidateRelativePathAcceptsDeviceNameLookalikes checks that the reserved
// list does not over-reach. A name that merely starts with a device name is an
// ordinary file, and refusing it would make the grammar unusable.
func TestValidateRelativePathAcceptsDeviceNameLookalikes(t *testing.T) {
	accepted := []string{
		"console", "null", "auxiliary", "printer",
		"com0", "com10", "com", "lpt", "lpt0", "lpt10",
		"conifer.txt", "nullable.txt",
	}

	for _, path := range accepted {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err != nil {
				t.Fatalf("ValidateRelativePath(%q) = %v, want nil", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsOverlongPath checks the whole-path cap.
func TestValidateRelativePathRejectsOverlongPath(t *testing.T) {
	overlong := strings.Repeat("a", MaxPathLength+1)
	err := ValidateRelativePath(overlong, false)
	if err == nil {
		t.Fatal("ValidateRelativePath(overlong) = nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "want at most") {
		t.Fatalf("ValidateRelativePath(overlong) = %v, want a length refusal", err)
	}
}

// buildPathOfLength builds a valid relative path of exactly total bytes, using
// components no longer than the per-component cap. It exists so the whole-path
// cap can be tested at its boundary without accidentally tripping the
// per-component cap first.
func buildPathOfLength(total int) string {
	var parts []string
	remaining := total
	for remaining > 256 {
		parts = append(parts, strings.Repeat("a", maxComponentLength))
		remaining -= maxComponentLength + 1
	}
	// remaining is in [1,256]. A single component covers up to 255 bytes; 256
	// needs two components plus the separator between them.
	if remaining <= maxComponentLength {
		parts = append(parts, strings.Repeat("a", remaining))
	} else {
		parts = append(parts, strings.Repeat("a", 128), strings.Repeat("a", 127))
	}
	return strings.Join(parts, "/")
}

// TestValidateRelativePathAcceptsMaxLength checks that the cap is inclusive, so
// a path of exactly the limit is not refused by an off-by-one.
func TestValidateRelativePathAcceptsMaxLength(t *testing.T) {
	exact := buildPathOfLength(MaxPathLength)
	if len(exact) != MaxPathLength {
		t.Fatalf("buildPathOfLength produced %d bytes, want %d", len(exact), MaxPathLength)
	}
	if err := ValidateRelativePath(exact, false); err != nil {
		t.Fatalf("ValidateRelativePath(exact max) = %v, want nil", err)
	}
}

// TestValidateRelativePathRejectsOverlongComponent checks the per-component
// cap, which is the common filesystem maximum: a longer component could never
// name a real file.
func TestValidateRelativePathRejectsOverlongComponent(t *testing.T) {
	overlong := strings.Repeat("a", maxComponentLength+1)
	err := ValidateRelativePath(overlong, false)
	if err == nil {
		t.Fatal("ValidateRelativePath(overlong component) = nil, want a refusal")
	}
	if !strings.Contains(err.Error(), "component") {
		t.Fatalf("ValidateRelativePath(overlong component) = %v, want a component refusal", err)
	}
}

// TestValidateRelativePathAllowRoot checks that only the empty path is governed
// by allowRoot, and that the empty path is refused when it is not set. Listing
// the root is a normal request; reading or stating the root is not a file
// operation at all.
func TestValidateRelativePathAllowRoot(t *testing.T) {
	if err := ValidateRelativePath("", true); err != nil {
		t.Fatalf("ValidateRelativePath(\"\", allowRoot=true) = %v, want nil", err)
	}
	if err := ValidateRelativePath("", false); err == nil {
		t.Fatal("ValidateRelativePath(\"\", allowRoot=false) = nil, want a refusal")
	}
}

// TestValidateRelativePathTreatsUnicodeSeparatorAsLiteral checks that a
// lookalike separator is an ordinary character rather than a separator. It is
// accepted as part of one component, which is what it is: a filename byte.
func TestValidateRelativePathTreatsUnicodeSeparatorAsLiteral(t *testing.T) {
	// U+2215 DIVISION SLASH and U+FF0F FULLWIDTH SOLIDUS are not path
	// separators on any platform, so they name a file rather than a directory.
	for _, path := range []string{"a\u2215b", "a\uFF0Fb"} {
		t.Run(path, func(t *testing.T) {
			if err := ValidateRelativePath(path, false); err != nil {
				t.Fatalf("ValidateRelativePath(%q) = %v, want nil", path, err)
			}
		})
	}
}

// TestValidateRelativePathRejectsEncodedSeparator checks that a percent-encoded
// separator is not decoded. The grammar sees the literal bytes, so `%2f` is a
// filename and never a directory boundary; a decoder anywhere in the path would
// turn one request into two different paths.
func TestValidateRelativePathRejectsEncodedSeparator(t *testing.T) {
	// `%2f` is accepted as a literal name, which is correct: nothing decodes
	// it. The test records that the fence never decodes, so the value that is
	// checked is the value that is opened.
	if err := ValidateRelativePath("a%2f..%2fb", false); err != nil {
		t.Fatalf("ValidateRelativePath(encoded) = %v, want nil because nothing decodes it", err)
	}
}
