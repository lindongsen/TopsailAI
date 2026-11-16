package main

// The record budget the Endpoint sends is not a bound it enforces, so nothing
// fails when it drifts away from what the shipped Provider CLI advertises. The
// comment above the constants states the relationship, and a comment is not
// executable: the operator and the next reader then learn a number that no longer
// describes the deployment.
//
// Two claims are checked here. The Endpoint's record budget must not exceed the
// provider's advertised budget, because a provider that enforced its own bound
// would refuse a request the Endpoint considers valid. And the comment must still
// say the budget is not a bound, because that sentence is the only thing stopping
// a future reader from reintroducing a record counter on the follow path.
//
// The provider is a separate main package, so its advertised value is read from
// source rather than imported. That is the same approach the install-layout guard
// uses for the post-install script: a value that lives in another binary cannot be
// linked, and reading it is what keeps the two sides from drifting silently.

import (
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// providerRecordBudgetPattern reads the advertised record budget out of the
// shipped Provider descriptor.
var providerRecordBudgetPattern = regexp.MustCompile(`MaxRecords:\s+([0-9_]+)`)

// recordBudgetCommentAnchor is the sentence the guard below assumes still exists.
// If the comment is rewritten, the guard fails instead of checking a sentence that
// is no longer there.
const recordBudgetCommentAnchor = "the follow path must therefore never treat it as a bound"

// TestEndpointRecordBudgetDoesNotExceedTheProviderBudget proves the Endpoint does
// not claim a record budget larger than the provider advertises.
//
// The Endpoint does not count records, so the value is currently inert. It becomes
// a real bound the moment a provider enforces its own advertised budget, and at
// that point an Endpoint value above the provider's would turn every long tail
// into a provider refusal. Keeping the Endpoint at or below the advertised value
// is what makes that future change safe instead of a silent regression.
func TestEndpointRecordBudgetDoesNotExceedTheProviderBudget(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, "providers/topsailai/descriptor.go")

	match := providerRecordBudgetPattern.FindStringSubmatch(source)
	if match == nil {
		t.Fatalf("providers/topsailai/descriptor.go declares no MaxRecords budget, so this guard cannot compare the two sides")
	}
	advertised, err := strconv.ParseInt(replaceUnderscores(match[1]), 10, 64)
	if err != nil {
		t.Fatalf("parse the provider record budget %q: %v", match[1], err)
	}
	if advertised < 1 {
		t.Fatalf("the provider advertises a record budget of %d, which the wire schema rejects", advertised)
	}
	if genericCLIMaxRecords > advertised {
		t.Fatalf("the Endpoint sends a record budget of %d while the provider advertises %d, so a provider that enforced its own bound would refuse a request the Endpoint considers valid",
			genericCLIMaxRecords, advertised)
	}
}

// TestRecordBudgetCommentKeepsTheNotABoundClaim proves the comment above the
// constants still states that the record budget is not a bound.
//
// The sentence is the only written record of why the follow path does not count
// records. Removing it leaves a constant named MaxRecords beside a scanner that
// ignores it, which reads as an oversight rather than a decision, and the next
// reader restores the counter that truncated every long tail.
func TestRecordBudgetCommentKeepsTheNotABoundClaim(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, "src/main/agent-cluster-endpoint/adapter_factory.go")
	if !strings.Contains(source, recordBudgetCommentAnchor) {
		t.Fatalf("src/main/agent-cluster-endpoint/adapter_factory.go no longer states %q, so the record budget reads as an unenforced oversight instead of a decision", recordBudgetCommentAnchor)
	}
}

// replaceUnderscores strips the digit separators Go allows in a numeric literal,
// so a budget written as 10_000 parses as a number.
func replaceUnderscores(value string) string {
	cleaned := make([]byte, 0, len(value))
	for index := 0; index < len(value); index++ {
		if value[index] == '_' {
			continue
		}
		cleaned = append(cleaned, value[index])
	}
	return string(cleaned)
}
