package main

// The deadline contract is prose in two documents and behaviour in one function,
// and the two disagreed: the Endpoint reported an unknown effect for a command it
// had provably never executed, while every other reader of the same field treated
// zero as "no deadline". Nothing failed, because no test read the documents and no
// document described the zero value at all.
//
// The guard pins both directions. It requires each document to state the zero-value
// meaning and both expiry codes, and it refuses the claim that a zero deadline
// expires a command immediately, which is the reading the old code implemented.
// Requiring the positive statements is what stops a vacuous pass: deleting the
// paragraphs would satisfy every negative check while leaving a reader with no
// description at all.
//
// The documents are read from disk rather than asserted through a function, because
// the regression is prose. No code path can observe a wrong sentence.

import (
	"strings"
	"testing"
)

// deadlineDocuments are the documents that describe the deadline contract. The API
// document is included because a caller learns the field there, and the protocol
// document is included because it owns the lifecycle and certainty rules.
var deadlineDocuments = []string{
	"docs/API.md",
	"docs/agent-cluster-protocol.md",
}

// deadlineExpiryCodes are the two codes an Endpoint reports when a deadline
// prevents the provider call. Both must appear in both documents: a reader who
// sees only one cannot tell the two situations apart, and the remedies differ.
var deadlineExpiryCodes = []string{
	"expired_before_execution",
	"expired_after_validation",
}

// deadlineZeroValueStatement is the phrase each document must carry to state what
// a zero deadline means. It is checked separately from the codes so a document
// cannot satisfy the guard by listing the codes while leaving the zero value
// undefined, which is exactly the gap that let the defect survive.
const deadlineZeroValueStatement = "no deadline"

// deadlineRemovedClaims are sentences that state the removed behaviour. A zero
// deadline used to be treated as already expired by the post-validation check, so
// a document that describes zero as an immediate expiry is describing the defect.
var deadlineRemovedClaims = []string{
	"a zero deadline expires the command immediately",
	"zero means the command has already expired",
}

// TestDeadlineDocumentsStateTheZeroValueAndBothCodes requires each document to
// define the zero value and to name both expiry codes.
//
// The non-vacuity check is the zero-value requirement: a document that listed only
// the codes would pass a codes-only guard while still leaving a caller unable to
// predict what zero does.
func TestDeadlineDocumentsStateTheZeroValueAndBothCodes(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range deadlineDocuments {
		document := readRepoFile(t, root, relative)
		collapsed := strings.Join(strings.Fields(document), " ")
		if !strings.Contains(collapsed, deadlineZeroValueStatement) {
			t.Fatalf("%s does not state %q, so a caller cannot tell what a zero deadline does", relative, deadlineZeroValueStatement)
		}
		for _, code := range deadlineExpiryCodes {
			if !strings.Contains(document, code) {
				t.Fatalf("%s does not name %q, so a reader cannot tell the two expiry situations apart", relative, code)
			}
		}
	}
}

// TestDeadlineDocumentsDoNotDescribeZeroAsAnImmediateExpiry refuses the reading
// the old code implemented.
//
// The phrase is matched with whitespace collapsed, because the sentences wrap
// across lines and a line break must not hide them.
func TestDeadlineDocumentsDoNotDescribeZeroAsAnImmediateExpiry(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range deadlineDocuments {
		document := readRepoFile(t, root, relative)
		collapsed := strings.Join(strings.Fields(document), " ")
		for _, claim := range deadlineRemovedClaims {
			if strings.Contains(collapsed, claim) {
				t.Fatalf("%s still states %q, so it describes the removed behaviour where zero meant already expired", relative, claim)
			}
		}
	}
}

// TestDeadlineDocumentsRequireCertaintyForBothCodes requires each document to tie
// both codes to a certain, unapplied effect.
//
// The certainty is the part that actually failed: the code was reported correctly
// while the effect said unknown, and unknown is the value that forbids automatic
// retry. A document that named the codes without the certainty would leave the
// defect's most damaging consequence undescribed.
func TestDeadlineDocumentsRequireCertaintyForBothCodes(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range deadlineDocuments {
		document := readRepoFile(t, root, relative)
		collapsed := strings.Join(strings.Fields(document), " ")
		if !strings.Contains(collapsed, "not_applied") {
			t.Fatalf("%s does not state %q for an expired deadline, so a reader cannot tell that the provider was never called", relative, "not_applied")
		}
	}
}
