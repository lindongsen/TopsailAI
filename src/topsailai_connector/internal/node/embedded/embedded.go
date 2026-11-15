// Package embedded holds the configuration a self-contained build compiles into
// the binary.
//
// The three variables are empty in a normal build, so a normal build behaves
// exactly as it did before this package existed. A packaging run fills them with
// `go build -ldflags "-X ..."`, and the Node then starts with no configuration
// file and no environment variable.
//
// # What this package does not do
//
// It does not encrypt anything. A value passed through `-X` is stored in the
// binary's data section as plain text, so `strings connector-node` recovers it.
// That is inherent to the mechanism and it is the accepted cost of a binary that
// runs on first start: the binary is the credential, and handing someone the
// binary hands them the channel gate. The Node compensates by refusing to serve
// its own executable through a scope, which is the one thing it can do about a
// secret it must carry.
//
// The policy is carried base64-encoded rather than as raw YAML. That is a
// quoting decision, not a secrecy one: a YAML document contains newlines and
// quotes, and a linker flag that has to survive a shell, a Makefile and a
// `go build` invocation is a flag that will eventually be mangled. Base64 has no
// character a shell treats specially, so the value arrives intact. It provides
// no confidentiality whatsoever.
package embedded

import (
	"encoding/base64"
	"fmt"
)

// ServerURL is the channel address the Node dials when the build embedded one.
//
// It is a plain string rather than a validated URL because validation belongs to
// LoadConfig, which is the one place a configuration value is checked. A package
// that validated its own input would be a second place for the rules to live.
var ServerURL string

// TunnelToken is the secret the Node presents in hello when the build embedded
// one.
//
// This is the value that makes the binary a credential. It is never logged, never
// written to a file and never echoed by a configuration dump, exactly as the
// environment-supplied value is not.
var TunnelToken string

// PolicyBase64 is the base64-encoded policy document the build embedded.
//
// Base64 is used for quoting, not for secrecy. See the package comment.
var PolicyBase64 string

// Enabled reports whether this build embedded any configuration at all.
//
// It is true when any of the three values is set, so a build that embedded only
// the Server URL is still recognised as an embedded build rather than silently
// treated as a normal one.
func Enabled() bool {
	return ServerURL != "" || TunnelToken != "" || PolicyBase64 != ""
}

// CarriesSecret reports whether this build embedded the tunnel token.
//
// The answer decides whether the running executable must be added to the deny
// list. A binary that carries no secret needs no entry, because reading it
// discloses nothing a caller could not already read from the source. A binary
// that carries the tunnel token must be refused, because the token is
// Server-wide: a caller who reads it can open a channel and impersonate any Node,
// not just this one.
func CarriesSecret() bool {
	return TunnelToken != ""
}

// Policy decodes the embedded policy document.
//
// An empty value returns a nil slice and no error, so a build that embedded no
// policy is distinguishable from a build whose policy failed to decode. A
// malformed value is an error rather than a panic: a packaging mistake must
// surface as a startup failure with a message, not as a crash with a stack trace
// on a machine the operator cannot see.
func Policy() ([]byte, error) {
	if PolicyBase64 == "" {
		return nil, nil
	}
	decoded, err := base64.StdEncoding.DecodeString(PolicyBase64)
	if err != nil {
		return nil, fmt.Errorf("decode the embedded policy: %w", err)
	}
	return decoded, nil
}
