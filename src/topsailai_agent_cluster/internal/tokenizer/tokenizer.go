// Package tokenizer counts and truncates text with the provider's own token
// counting rule.
//
// It exists as one shared package because two layers need the same rule for
// different purposes: the adapter reports how large a stored body is, and the
// renderer bounds how much of a body is displayed. Two copies of the encoder
// would let those two numbers disagree about the same text, and a bound computed
// with a different rule than the count printed beside it is a contradiction the
// operator cannot resolve.
//
// The counting rule itself is provider detail. It is named here, in one place,
// rather than derived from a model, because the cluster must reproduce the
// provider's number rather than the number some other model would produce.
package tokenizer

import (
	"sync"

	tiktoken "github.com/pkoukk/tiktoken-go"
	tiktokenloader "github.com/pkoukk/tiktoken-go-loader"
)

// encodingName is the encoding the provider's own counter uses.
const encodingName = "cl100k_base"

// ellipsis marks text that a bound removed.
//
// It is exported so every bound uses one marker. An operator then sees a single
// signal for "text is missing" regardless of which bound shortened the body.
const ellipsis = "..."

var (
	// encodingOnce builds the encoder at most once per process.
	//
	// Loading the vocabulary costs about 200ms, which is a fifth of the whole
	// messages budget. Building it per message would spend the budget on setup and
	// leave nothing for the read itself.
	encodingOnce sync.Once
	// encoding is nil when the vocabulary could not be loaded, so a counting
	// failure degrades to "no count claimed" instead of failing the read.
	encoding *tiktoken.Tiktoken
)

// encoder returns the shared encoder, or nil when it cannot be built.
//
// A nil result is a degraded state, not an error: callers must treat it as "no
// count claimed" and must never truncate on the strength of a count they do not
// have.
func encoder() *tiktoken.Tiktoken {
	encodingOnce.Do(func() {
		// The offline loader is installed before the encoding is requested, because
		// the default loader downloads the vocabulary at first use. A packaged node
		// may have no route to the internet, so a download would make the count
		// depend on network reachability.
		tiktoken.SetBpeLoader(tiktokenloader.NewOfflineLoader())
		loaded, err := tiktoken.GetEncoding(encodingName)
		if err != nil {
			return
		}
		encoding = loaded
	})
	return encoding
}

// Count reports how many model tokens one body contains.
//
// The provider's own human-readable surface prints this number next to each
// message, so the cluster reproduces it rather than inventing a different
// measure.
//
// A load or encode failure returns zero, which the protocol documents as "no
// count claimed" rather than as a measured empty body: a display detail must
// never turn a readable conversation into a failed read.
func Count(content string) int {
	if content == "" {
		return 0
	}
	loaded := encoder()
	if loaded == nil {
		return 0
	}
	// EncodeOrdinary is used rather than Encode because the provider calls
	// encoding.encode(text) with no special-token arguments, which treats every
	// special token as ordinary text. Encode would instead panic on a body that
	// happens to contain a token-looking string, and a conversation is untrusted
	// text that may contain anything.
	return len(loaded.EncodeOrdinary(content))
}

// Truncate shortens one body to a token bound.
//
// The cut is made on a token boundary and the surviving tokens are decoded back
// to text, so the result is always valid UTF-8 rather than a byte slice of an
// encoded stream.
//
// The bound is skipped entirely when the encoder is unavailable. That is
// load-bearing: Count reports zero both for an empty body and for a failed
// encoder, so truncating on a zero count would erase every message on a host
// where the vocabulary could not be loaded. A display bound must never turn a
// readable conversation into an empty one.
//
// A zero bound means no truncation, matching the character bound and the
// cluster's own convention.
func Truncate(content string, maxTokens int) string {
	if maxTokens <= 0 || content == "" {
		return content
	}
	loaded := encoder()
	if loaded == nil {
		return content
	}
	tokens := loaded.EncodeOrdinary(content)
	if len(tokens) <= maxTokens {
		return content
	}
	return loaded.Decode(tokens[:maxTokens]) + ellipsis
}
