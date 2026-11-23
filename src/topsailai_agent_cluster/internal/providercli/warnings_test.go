package providercli

import (
	"strings"
	"testing"
)

// TestOperationResultBoundsWarnings proves the warning list is bounded in both
// count and length.
//
// A warning is rendered to the operator's terminal, so an unbounded list of
// unbounded strings would let a provider flood the surface. The bound is enforced
// here rather than only in the schema because the schema is documentation for an
// external implementer, while this check is what actually refuses the response.
func TestOperationResultBoundsWarnings(t *testing.T) {
	// Both slices are filled, because an empty string is itself a rejected
	// warning: a bare make() would test the empty-warning rule instead of the
	// count rule, and the count case would fail for the wrong reason.
	atLimit := make([]string, MaxWarnings)
	for i := range atLimit {
		atLimit[i] = "warning"
	}
	tooMany := make([]string, MaxWarnings+1)
	for i := range tooMany {
		tooMany[i] = "warning"
	}
	cases := []struct {
		name     string
		warnings []string
		wantErr  string
	}{
		{"at the count limit", atLimit, ""},
		{"above the count limit", tooMany, "above the limit"},
		{"empty warning", []string{""}, "empty warning"},
		{"whitespace-only warning", []string{"   "}, "empty warning"},
		{"at the length limit", []string{strings.Repeat("a", MaxWarningBytes)}, ""},
		{"above the length limit", []string{strings.Repeat("a", MaxWarningBytes+1)}, "exceeds"},
		{"invalid UTF-8", []string{"\xff\xfe"}, "valid UTF-8"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			result := OperationResult{
				DeliveryBoundary:          "submitted",
				EffectCertainty:           "acknowledged",
				ProviderOutcome:           "accepted",
				ProviderResponseTruncated: false,
				Warnings:                  testCase.warnings,
			}
			err := result.validate()
			if testCase.wantErr == "" {
				if err != nil {
					t.Fatalf("warnings %v were refused: %v", testCase.warnings, err)
				}
				return
			}
			if err == nil {
				t.Fatalf("warnings %v were accepted, want an error containing %q", testCase.warnings, testCase.wantErr)
			}
			if !strings.Contains(err.Error(), testCase.wantErr) {
				t.Fatalf("error %q does not contain %q", err.Error(), testCase.wantErr)
			}
		})
	}
}
