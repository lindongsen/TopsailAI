// Package version reports the identity of one cluster binary.
//
// The values are injected at build time through -ldflags -X, so a packaged
// binary can state which release it came from while a binary that was never
// packaged cannot claim a release identity. They are variables rather than
// constants because -X is silently ineffective on a constant: the build
// succeeds, exits zero, and leaves the literal in place.
package version

import (
	"encoding/json"
	"fmt"
	"io"
	"runtime"
	"strings"
)

// Version is the release the binary was built from.
//
// The default is deliberately not version-shaped, because a binary that was
// never packaged must not claim a release identity. An operator who sees this
// value knows the binary is a local build rather than a shipped one.
var Version = "0.0.0-unpackaged"

// Commit is the source revision the binary was built from.
var Commit = "unknown"

// BuildTime is the UTC instant the binary was built, in RFC 3339 form.
var BuildTime = "unknown"

// Identity is the machine-readable form of the same facts. It is a struct rather
// than a map so the field order is stable and a script can rely on the shape.
type Identity struct {
	Component string `json:"component"`
	Version   string `json:"version"`
	Commit    string `json:"commit"`
	Built     string `json:"built"`
	Go        string `json:"go"`
	OS        string `json:"os"`
	Arch      string `json:"arch"`
}

// Current returns the identity of one component. The component name is the
// executable name, so the same helper serves every binary without each one
// inventing its own layout.
func Current(component string) Identity {
	return Identity{
		Component: component,
		Version:   Version,
		Commit:    Commit,
		Built:     BuildTime,
		Go:        runtime.Version(),
		OS:        runtime.GOOS,
		Arch:      runtime.GOARCH,
	}
}

// Write renders the identity for a human who is diagnosing a deployment.
//
// The commit and the build time are printed because they are the facts that
// actually distinguish two builds of the same release; a version number alone
// cannot tell a rebuilt binary from the one that was shipped.
func Write(out io.Writer, component string) error {
	identity := Current(component)
	_, err := fmt.Fprintf(out, "%s %s\n  commit:  %s\n  built:   %s\n  go:      %s %s/%s\n",
		identity.Component, identity.Version, identity.Commit, identity.Built, identity.Go, identity.OS, identity.Arch)
	return err
}

// WriteJSON renders the same facts as one structured line, so a script can read
// the version without parsing the human-readable layout.
func WriteJSON(out io.Writer, component string) error {
	encoded, err := json.Marshal(Current(component))
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(out, "%s\n", encoded)
	return err
}

// Requested reports whether the raw arguments ask for the binary identity.
//
// The request is detected on the raw arguments rather than through the flag set
// because Go's flag package stops parsing at the first positional argument, so a
// command-level "-v" would never reach the flag set at all. A "--" terminator
// ends the scan: after it every token is data, so
// "exec <endpoint> <resource> <generation> -- ls -v" still passes -v to ls.
//
// valueOptions names the options that consume the following argument, so a value
// that happens to be "-v" is not misread as the flag. The next argument is
// consumed unconditionally, because that is what Go's flag package does: for a
// non-boolean option the following argument is its value even when it begins with
// a dash.
//
// Every caller must pass its own option set. A nil map is only correct for a
// program that accepts no value options at all, and no cluster binary is such a
// program: "--tls-certificate-file -v" names a file called "-v", and a scan that
// ignored the value would answer a version request the operator never made. The
// daemons derive the set from the same declaration their parser uses, so the two
// cannot disagree.
func Requested(args []string, valueOptions map[string]bool) bool {
	for index := 0; index < len(args); index++ {
		arg := args[index]
		if arg == "--" {
			return false
		}
		if arg == "--version" || arg == "-v" {
			return true
		}
		if !strings.HasPrefix(arg, "-") || arg == "-" {
			continue
		}
		name, hasValue := SplitOptionName(arg)
		if !hasValue && valueOptions[name] && index+1 < len(args) {
			index++
		}
	}
	return false
}

// SplitOptionName reports the option name without its leading dashes and whether
// the value was attached with "=".
//
// It is exported because the CLI already had this exact helper for its own raw
// argument scans, and a second copy would drift: the two would disagree the first
// time an option spelling changed, and the disagreement would be invisible because
// both copies would still compile. The CLI's own helper now delegates here, so one
// implementation serves every raw scan in the program.
func SplitOptionName(arg string) (string, bool) {
	name := strings.TrimLeft(arg, "-")
	if idx := strings.Index(name, "="); idx >= 0 {
		return name[:idx], true
	}
	return name, false
}
