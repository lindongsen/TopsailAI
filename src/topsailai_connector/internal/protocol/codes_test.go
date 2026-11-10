package protocol

import "testing"

// TestCodeNamesMatchDocumentation checks that every code carries the name the
// API document promises. A caller matches on the name, so a renamed code is a
// breaking change even when the number stays the same.
func TestCodeNamesMatchDocumentation(t *testing.T) {
	cases := []struct {
		code Code
		name string
	}{
		{code: CodeSuccess, name: "success"},
		{code: CodeInvalidArgument, name: "invalid_argument"},
		{code: CodeUnauthenticated, name: "unauthenticated"},
		{code: CodeNodeOffline, name: "node_offline"},
		{code: CodeNodeTimeout, name: "node_timeout"},
		{code: CodeDenied, name: "denied"},
		{code: CodeNotFound, name: "not_found"},
		{code: CodeUnsupportedOperation, name: "unsupported_operation"},
		{code: CodeTooLarge, name: "too_large"},
		{code: CodeInternal, name: "internal"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := testCase.code.Name(); got != testCase.name {
				t.Fatalf("Name() = %q, want %q", got, testCase.name)
			}
		})
	}
}

// TestCodeNumbersMatchDocumentation checks the numeric values, because the
// document publishes them and a client may branch on the number instead of the
// name.
func TestCodeNumbersMatchDocumentation(t *testing.T) {
	cases := []struct {
		code   Code
		number int
	}{
		{code: CodeSuccess, number: 0},
		{code: CodeInvalidArgument, number: 1001},
		{code: CodeUnauthenticated, number: 1002},
		{code: CodeNodeOffline, number: 1003},
		{code: CodeNodeTimeout, number: 1004},
		{code: CodeDenied, number: 1005},
		{code: CodeNotFound, number: 1006},
		{code: CodeUnsupportedOperation, number: 1007},
		{code: CodeTooLarge, number: 1008},
		{code: CodeInternal, number: 1009},
	}

	for _, testCase := range cases {
		if int(testCase.code) != testCase.number {
			t.Fatalf("%s = %d, want %d", testCase.code.Name(), int(testCase.code), testCase.number)
		}
	}
}

// TestCodeNamesAreUnique checks that no two codes share a name, because a
// duplicate name would make a caller's branch ambiguous.
func TestCodeNamesAreUnique(t *testing.T) {
	seen := make(map[string]Code)
	all := []Code{
		CodeSuccess, CodeInvalidArgument, CodeUnauthenticated, CodeNodeOffline,
		CodeNodeTimeout, CodeDenied, CodeNotFound, CodeUnsupportedOperation,
		CodeTooLarge, CodeInternal,
	}

	for _, code := range all {
		name := code.Name()
		if previous, ok := seen[name]; ok {
			t.Fatalf("codes %d and %d share the name %q", int(previous), int(code), name)
		}
		seen[name] = code
	}
}

// TestUnknownCodeIsNotSuccess checks that an unassigned code is never reported
// as success, because a zero value that means success would turn a programming
// mistake into a silent success.
func TestUnknownCodeIsNotSuccess(t *testing.T) {
	unknown := Code(9999)
	if unknown.IsSuccess() {
		t.Fatal("IsSuccess() = true for an unassigned code, want false")
	}
	if unknown.Name() != "unknown" {
		t.Fatalf("Name() = %q, want %q", unknown.Name(), "unknown")
	}
}

// TestRetryableCodes checks the retry classification. A refusal must not be
// retryable, because retrying a refusal turns a policy decision into a load
// problem on the Node.
func TestRetryableCodes(t *testing.T) {
	cases := []struct {
		code      Code
		retryable bool
	}{
		{code: CodeSuccess, retryable: false},
		{code: CodeInvalidArgument, retryable: false},
		{code: CodeUnauthenticated, retryable: false},
		{code: CodeNodeOffline, retryable: true},
		{code: CodeNodeTimeout, retryable: true},
		{code: CodeDenied, retryable: false},
		{code: CodeNotFound, retryable: false},
		{code: CodeUnsupportedOperation, retryable: false},
		{code: CodeTooLarge, retryable: false},
		{code: CodeInternal, retryable: true},
	}

	for _, testCase := range cases {
		t.Run(testCase.code.Name(), func(t *testing.T) {
			if got := testCase.code.Retryable(); got != testCase.retryable {
				t.Fatalf("Retryable() = %v, want %v", got, testCase.retryable)
			}
		})
	}
}

// TestCodeErrorDoesNotLeakDetail checks that a code used as an error carries
// only the name and the number. An error string is the easiest place for a path
// or a secret to reach a log, so the representation is fixed.
func TestCodeErrorDoesNotLeakDetail(t *testing.T) {
	got := CodeDenied.Error()
	want := "denied (1005)"
	if got != want {
		t.Fatalf("Error() = %q, want %q", got, want)
	}
}
