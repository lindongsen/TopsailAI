package adapter

import (
	"errors"
	"os/exec"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// BoundedProviderResponse applies the receipt bound to one provider document.
//
// The provider's own answer is opaque evidence, so it is carried verbatim up to
// the protocol bound. Truncation backs off to a rune boundary so the stored
// string stays valid UTF-8, and the flag reports that the document is
// incomplete: a shortened provider answer must never be presented as complete.
func BoundedProviderResponse(document string) (string, bool) {
	if len(document) <= protocol.MaxProviderResponseBytes {
		return document, false
	}
	limit := protocol.MaxProviderResponseBytes
	for limit > 0 && !utf8.RuneStart(document[limit]) {
		limit--
	}
	return document[:limit], true
}

// ProviderFailureText returns the provider's own stderr for a failed invocation.
//
// A non-zero exit is the only signal that the call failed, and the provider's
// stderr is the only evidence of why. exec.ExitError carries the captured
// stderr, so errors.As reaches it through any wrapping.
func ProviderFailureText(err error) string {
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && len(exitErr.Stderr) > 0 {
		return string(exitErr.Stderr)
	}
	return ""
}
