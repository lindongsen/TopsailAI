package bdd

import (
	"os"
	"strings"
	"testing"
)

// mockProviderSource is the mock provider's source file, relative to this
// package directory. The guard reads it as text because the fact it checks is a
// literal in that file, not a value this package can import.
const mockProviderSource = "../../providers/mock/main.go"

// TestMessagesFixtureIsDistinguishableFromTheMockDefault fails when the body the
// messages scenarios configure is also the body the mock provider answers by
// default.
//
// The coincidence is what made the unwrapping scenario unable to fail. The mock
// falls back to a default body when no --messages-body argument arrives, and that
// default used to be the prose "topsailai.task" plus "the operator wrote this",
// which contains both strings the scenario asserts. Breaking the argv channel in
// providerFaultArgs therefore left the scenario green: the configured record never
// reached the provider, the mock answered with its default, and the assertion
// compared that default with itself.
//
// The scenario now fails when the channel breaks, but only because the fixture
// values are distinctive. If a later change made the mock default equal to the
// fixture again, the scenario would silently stop proving anything, and no test
// would notice. This guard is the only thing that keeps the two apart, so it
// asserts the disjointness directly instead of trusting the current literals.
func TestMessagesFixtureIsDistinguishableFromTheMockDefault(t *testing.T) {
	source, err := os.ReadFile(mockProviderSource)
	if err != nil {
		t.Fatalf("read %s: %v", mockProviderSource, err)
	}
	text := string(source)

	// The fixture must be a real step record, because a prose body would make the
	// unwrapping scenario pass without the adapter unwrapping anything.
	if !strings.Contains(messagesStepRecord, "step_name") {
		t.Fatalf("the configured body %q is not a step record, so the unwrapping scenario proves nothing", messagesStepRecord)
	}

	// Each expected value must be absent from the mock source. Absence is the
	// property that matters: the mock cannot answer with a value it does not
	// contain, so a default that coincides with the fixture is impossible while
	// this holds.
	for name, value := range map[string]string{
		"step label":    messagesStepLabel,
		"operator text": messagesStepText,
	} {
		if strings.Contains(text, value) {
			t.Fatalf("the mock provider source contains the %s %q, so its default answer can satisfy the assertion without the configured body arriving; the fixture must stay distinguishable from every value the mock answers by default", name, value)
		}
	}
}
