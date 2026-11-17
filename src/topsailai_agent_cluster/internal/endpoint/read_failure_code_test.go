package endpoint

import (
	"errors"
	"fmt"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// codedTestError is a stand-in for a rejection that carries its own code. It
// exists so this test does not depend on the package that produces the real
// rejection, which is the same reason the production helper recognises the code
// through an interface rather than an import.
type codedTestError struct {
	code    string
	message string
}

// Error renders the message.
func (e *codedTestError) Error() string { return e.message }

// ErrorCode reports the carried code.
func (e *codedTestError) ErrorCode() string { return e.code }

// TestReadFailureCodeClassifiesARejectedIdentityAsACallerError proves a request
// that named the wrong identity is not reported as a provider failure.
//
// The caller supplied the wrong kind of identity, so the remedy is to supply the
// right one. Reporting it as a provider failure sends the operator to investigate
// a provider that was never invoked, which is the defect this guards.
func TestReadFailureCodeClassifiesARejectedIdentityAsACallerError(t *testing.T) {
	err := &codedTestError{code: protocol.InvalidTarget, message: "provider_resource_key must be a provider-private key"}
	got := readFailureCode(err, "", protocol.MessagesProviderError)
	if got != protocol.InvalidTarget {
		t.Fatalf("readFailureCode=%q want=%q", got, protocol.InvalidTarget)
	}
	if got == protocol.MessagesProviderError {
		t.Fatalf("a rejected identity was reported as a provider failure: %q", got)
	}
}

// TestReadFailureCodeKeepsTheOriginalPrecedence proves the new classification did
// not displace the two conditions that already outranked the provider default.
//
// A capacity refusal still wins over a reported code, because the adapter never
// reached the provider and so has no provider evidence to report. A reported code
// still wins over the provider default, because the adapter's own answer is
// stronger evidence than a fallback.
func TestReadFailureCodeKeepsTheOriginalPrecedence(t *testing.T) {
	for _, item := range []struct {
		name         string
		err          error
		reported     string
		providerCode string
		want         string
	}{
		{
			name:         "capacity outranks a reported code",
			err:          adapter.ErrBusy,
			reported:     protocol.MessagesSessionNotFound,
			providerCode: protocol.MessagesProviderError,
			want:         protocol.AdapterBusy,
		},
		{
			name:         "capacity outranks a rejected identity",
			err:          fmt.Errorf("wrapped: %w", adapter.ErrBusy),
			providerCode: protocol.MessagesProviderError,
			want:         protocol.AdapterBusy,
		},
		{
			name:         "a reported code outranks the provider default",
			err:          errors.New("provider failed"),
			reported:     protocol.MessagesSessionNotFound,
			providerCode: protocol.MessagesProviderError,
			want:         protocol.MessagesSessionNotFound,
		},
		{
			name:         "an unclassified error keeps the provider default",
			err:          errors.New("provider failed"),
			providerCode: protocol.MessagesProviderError,
			want:         protocol.MessagesProviderError,
		},
		{
			name:         "a coded error with another code keeps the provider default",
			err:          &codedTestError{code: "some_other_code", message: "other"},
			providerCode: protocol.MessagesProviderError,
			want:         protocol.MessagesProviderError,
		},
	} {
		t.Run(item.name, func(t *testing.T) {
			got := readFailureCode(item.err, item.reported, item.providerCode)
			if got != item.want {
				t.Fatalf("readFailureCode=%q want=%q", got, item.want)
			}
		})
	}
}

// TestReadFailureCodeRecognisesAWrappedRejection proves the classification
// survives the wrapping the adapter applies on the way out.
//
// The adapter wraps a contract-validation failure with its own context, so a check
// that only inspected the outermost error would miss the rejection and fall back
// to the provider default. This is the shape the real path produces.
func TestReadFailureCodeRecognisesAWrappedRejection(t *testing.T) {
	inner := &codedTestError{code: protocol.InvalidTarget, message: "provider_resource_key must be a provider-private key"}
	wrapped := fmt.Errorf("validate provider query request: %w", inner)
	got := readFailureCode(wrapped, "", protocol.MessagesProviderError)
	if got != protocol.InvalidTarget {
		t.Fatalf("readFailureCode=%q want=%q for a wrapped rejection", got, protocol.InvalidTarget)
	}
}
