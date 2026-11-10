package node

import (
	"fmt"
	"strings"
)

// MaxPathLength bounds the path a caller may send. An unbounded path is a
// memory and log problem before it is a security problem, and no legitimate
// relative path inside a scope comes close to this limit.
const MaxPathLength = 4096

// maxComponentLength bounds one path component. The limit is the common
// filesystem maximum, so a longer component could never name a real file and
// refusing it early keeps the grammar honest.
const maxComponentLength = 255

// reservedDeviceNames are the Windows device names that resolve to a device
// regardless of the directory they appear in. They are rejected on every
// platform rather than only on Windows, because a path that means one thing on
// Linux and another on Windows is a path the policy author cannot reason about.
//
// The list is checked case-insensitively and with any extension stripped, since
// Windows treats `NUL`, `nul` and `NUL.txt` as the same device.
var reservedDeviceNames = map[string]struct{}{
	"con":  {},
	"prn":  {},
	"aux":  {},
	"nul":  {},
	"com1": {}, "com2": {}, "com3": {}, "com4": {}, "com5": {},
	"com6": {}, "com7": {}, "com8": {}, "com9": {},
	"lpt1": {}, "lpt2": {}, "lpt3": {}, "lpt4": {}, "lpt5": {},
	"lpt6": {}, "lpt7": {}, "lpt8": {}, "lpt9": {},
}

// ValidateRelativePath checks the grammar of a caller-supplied path without
// touching the filesystem.
//
// The grammar is deliberately small and every violation is a refusal rather than
// a normalisation. Normalising would mean the checked name and the opened name
// are produced by two different pieces of code, and the difference between them
// is where a fence bug lives.
//
// allowRoot permits the empty path, which addresses the scope root itself. Only
// `file.list` sets it: listing the root is a normal request, while reading or
// stating the root is not a file operation at all.
func ValidateRelativePath(path string, allowRoot bool) error {
	if path == "" {
		if allowRoot {
			return nil
		}
		return fmt.Errorf("path is empty; an empty path addresses the scope root, which is not a file")
	}
	if len(path) > MaxPathLength {
		return fmt.Errorf("path is %d bytes, want at most %d", len(path), MaxPathLength)
	}

	// A leading separator is an absolute path. The check is on the raw first
	// byte rather than on filepath.IsAbs, because filepath.IsAbs answers for the
	// host platform only: on Linux it accepts `C:\Windows` as relative.
	if path[0] == '/' || path[0] == '\\' {
		return fmt.Errorf("path is absolute; an absolute path addresses something the policy never named")
	}

	for index := 0; index < len(path); index++ {
		character := path[index]
		switch {
		case character == 0:
			return fmt.Errorf("path contains a NUL byte; a NUL truncates the name at the syscall boundary, so the checked name and the opened name differ")
		case character == '\\':
			return fmt.Errorf("path contains a backslash; on Windows a backslash is a separator, so accepting it would make one request mean two things")
		case character == ':':
			return fmt.Errorf("path contains a colon; on Windows a colon introduces a drive or an alternate data stream")
		case character < 0x20 || character == 0x7f:
			return fmt.Errorf("path contains a control character at byte %d", index)
		}
	}

	components := strings.Split(path, "/")
	for _, component := range components {
		if err := validateComponent(component); err != nil {
			return err
		}
	}
	return nil
}

// validateComponent checks one path component. An empty component is refused
// rather than collapsed, so `a//b` is a rejection instead of a second spelling
// of `a/b`: a deny list compared against one spelling would be bypassed by the
// other.
func validateComponent(component string) error {
	if component == "" {
		return fmt.Errorf("path contains an empty component; a doubled separator is a second spelling of the same name")
	}
	if component == "." {
		return fmt.Errorf("path contains a %q component; it is refused rather than normalised", ".")
	}
	if component == ".." {
		return fmt.Errorf("path contains a %q component; traversal is the primary escape attempt", "..")
	}
	if len(component) > maxComponentLength {
		return fmt.Errorf("path component is %d bytes, want at most %d", len(component), maxComponentLength)
	}

	last := component[len(component)-1]
	if last == '.' {
		return fmt.Errorf("path component %q ends with a dot; Windows strips it, so the checked name and the opened name differ", component)
	}
	if last == ' ' {
		return fmt.Errorf("path component %q ends with a space; Windows strips it, so the checked name and the opened name differ", component)
	}
	if component[0] == ' ' {
		return fmt.Errorf("path component %q starts with a space; a name that differs from what a policy author sees is a name they cannot reason about", component)
	}

	if isReservedDeviceName(component) {
		return fmt.Errorf("path component %q is a reserved device name; it resolves to a device regardless of the directory", component)
	}
	return nil
}

// isReservedDeviceName reports whether a component names a Windows device. The
// extension is stripped first, because `NUL.txt` is the same device as `NUL`.
func isReservedDeviceName(component string) bool {
	base := component
	if dot := strings.IndexByte(base, '.'); dot >= 0 {
		base = base[:dot]
	}
	_, reserved := reservedDeviceNames[strings.ToLower(base)]
	return reserved
}
