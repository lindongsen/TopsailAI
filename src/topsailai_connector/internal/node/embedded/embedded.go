// Package embedded holds the configuration a self-contained build compiles into
// the binary.
//
// The variables are empty in a normal build, so a normal build behaves exactly as
// it did before this package existed. A packaging run fills them with
// `go build -ldflags "-X ..."`, and the Node then starts with no configuration
// file and no environment variable.
//
// # Seeds, not authorities
//
// The node id and the node credential are seeds. On first start the Node writes the
// embedded value into the identity file and the credential file, and from then on
// the file is the authority: a file that already exists wins, `regenerate` still
// replaces the address, and `credential add` / `credential remove` still edit the
// set. Embedding them therefore does not remove any runtime capability; it only
// decides what the first write contains, which is what lets an operator know the
// address and the secret before the artifact leaves the build host.
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

	"topsailai_connector/internal/security"
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

// NodeID is the node id the build embedded, used as the seed for the identity file
// on first start.
//
// It is a seed rather than an authority. The identity file remains the value the
// running Node answers to, so `regenerate` still works and a file that already
// exists still wins. The embedded value only decides what the first write contains,
// which is what lets an operator know the address before the artifact leaves the
// build host.
var NodeID string

// Credential is the node credential the build embedded, in `key_id.secret` form,
// used as the seed for the credential file on first start.
//
// It is a seed for the same reason NodeID is, and it is a secret for the same reason
// TunnelToken is: it authorizes every operation on this Node and never expires. A
// build that carries it must therefore refuse to serve its own executable, which is
// what CarriesSecret reports.
var Credential string

// Enabled reports whether this build embedded any configuration at all.
//
// It is true when any value is set, so a build that embedded only the Server URL is
// still recognised as an embedded build rather than silently treated as a normal
// one.
func Enabled() bool {
	return ServerURL != "" || TunnelToken != "" || PolicyBase64 != "" ||
		NodeID != "" || Credential != ""
}

// CarriesSecret reports whether this build embedded a secret.
//
// The answer decides whether the running executable must be added to the deny
// list. A binary that carries no secret needs no entry, because reading it
// discloses nothing a caller could not already read from the source. A binary
// that carries one must be refused, because both secrets it can carry are
// dangerous to a reader: the tunnel token is Server-wide, so a caller who reads it
// can open a channel and impersonate any Node, and the node credential authorizes
// every operation on this Node and never expires.
func CarriesSecret() bool {
	return TunnelToken != "" || Credential != ""
}

// IdentitySeed returns the node id to write on first start, or an empty string when
// the build embedded none.
//
// A malformed value is an error rather than a silent fallback to a random
// identifier. A packaging mistake that produced a random address would look like a
// working Node whose address the operator cannot find, which is the failure this
// whole feature exists to prevent.
func IdentitySeed() (string, error) {
	if NodeID == "" {
		return "", nil
	}
	if err := security.ValidateNodeID(NodeID); err != nil {
		return "", fmt.Errorf("embedded node id: %w", err)
	}
	return NodeID, nil
}

// CredentialSeed returns the credential to write on first start, or a zero value
// when the build embedded none.
//
// The value is parsed by the same rule a credential read from a file is parsed by,
// so an embedded credential and a stored one cannot disagree about what a valid
// credential is.
func CredentialSeed() (security.Credential, error) {
	if Credential == "" {
		return security.Credential{}, nil
	}
	parsed, err := security.ParseCredential(Credential)
	if err != nil {
		return security.Credential{}, fmt.Errorf("embedded node credential: %w", err)
	}
	return parsed, nil
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
