package main

// The Endpoint must be able to run with no configured Adapter. A fresh install
// and a Provider CLI rollout both pass through that state, and an operator has to
// be able to verify the channel and the deployment before any Adapter exists. The
// parser therefore accepts an empty adapter list, and the documents say so.
//
// Nothing parses those documents at runtime, so a document that contradicts the
// parser produces no failure anywhere. The operator reads that an empty array is
// rejected, omits the variable instead of setting it explicitly, and never learns
// that the state they wanted is supported. Only reading the text can assert that
// the document and the parser agree.
//
// The parser is called rather than described, so a change that starts rejecting
// the empty list fails this guard at its premise instead of silently making the
// document wrong.

import (
	"regexp"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/config"
)

const zeroAdapterEnvironmentDocument = "docs/Environment_Variables.md"

// zeroAdapterLifecycleDocuments are the documents that describe what a
// zero-Adapter Endpoint does after startup. They are listed explicitly rather
// than discovered by a repository walk, so a renamed file fails loudly instead of
// silently shrinking the covered set.
var zeroAdapterLifecycleDocuments = []string{
	"docs/agent-cluster-adapters.md",
	"docs/agent-cluster-architecture.md",
}

// zeroAdapterRejectionPattern matches a claim that the empty adapter array is
// rejected. The parser accepts it, so such a claim sends an operator away from a
// supported configuration.
var zeroAdapterRejectionPattern = regexp.MustCompile(`(?i)rejects? an empty (array|list)`)

// zeroAdapterAcceptancePattern matches a statement that the empty array is
// accepted. The surrounding wording is not pinned; the presence of the statement
// is, because without it a reader cannot tell whether zero Adapters is supported.
var zeroAdapterAcceptancePattern = regexp.MustCompile(`(?i)empty (array|list) is accepted`)

// zeroAdapterParagraph returns the line number and text of the paragraph that
// carries an anchor phrase. A claim that spans a wrapped sentence cannot be
// checked one line at a time, so the paragraph is the unit. The document path is
// a parameter and appears in the failure message, because a shared helper that
// names one fixed document blames the wrong file when it is reused.
func zeroAdapterParagraph(t *testing.T, document, path, anchor string) (int, string) {
	t.Helper()
	offset := 0
	for _, paragraph := range strings.Split(document, "\n\n") {
		if index := strings.Index(paragraph, anchor); index >= 0 {
			return lineAt(document, offset+index), paragraph
		}
		offset += len(paragraph) + 2
	}
	t.Fatalf("%s holds no paragraph containing %q, so this guard checked nothing", path, anchor)
	return 0, ""
}

// TestZeroAdapterStartupIsDocumented pins the property that the environment
// reference does not contradict the parser about the empty adapter list. The
// parser is the premise: it is called first, so a change that starts rejecting
// the empty list fails here rather than leaving a document that quietly became
// wrong.
func TestZeroAdapterStartupIsDocumented(t *testing.T) {
	adapters, err := config.ParseAdapters("[]")
	if err != nil {
		t.Fatalf("ParseAdapters now rejects the empty list (%v), so the documents that describe a zero-Adapter Endpoint as supported are wrong", err)
	}
	if len(adapters) != 0 {
		t.Fatalf("ParseAdapters returned %d adapter(s) for an empty list, so this guard checked nothing", len(adapters))
	}

	root := repoRoot(t)
	document := readRepoFile(t, root, zeroAdapterEnvironmentDocument)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", zeroAdapterEnvironmentDocument)
	}

	line, paragraph := zeroAdapterParagraph(t, document, zeroAdapterEnvironmentDocument, "empty array")
	if match := zeroAdapterRejectionPattern.FindString(paragraph); match != "" {
		t.Fatalf("%s:%d states %q, but ParseAdapters accepts an empty list and internal/config/adapters_test.go asserts it, so an operator is told that a supported configuration is refused", zeroAdapterEnvironmentDocument, line, match)
	}
	if !zeroAdapterAcceptancePattern.MatchString(paragraph) {
		t.Fatalf("%s:%d describes the empty array without stating that it is accepted, so an operator cannot tell whether zero Adapters is a supported configuration", zeroAdapterEnvironmentDocument, line)
	}
}

// TestZeroAdapterHealthIsDocumented pins the second half of the claim: a
// zero-Adapter Endpoint stays observable after startup. Each lifecycle document
// must say what the Endpoint does once it has no Adapter, and at least one must
// state that it reports health, because "connected" alone does not tell an
// operator whether the node is healthy.
func TestZeroAdapterHealthIsDocumented(t *testing.T) {
	root := repoRoot(t)
	healthStated := false
	for _, path := range zeroAdapterLifecycleDocuments {
		document := readRepoFile(t, root, path)
		if strings.TrimSpace(document) == "" {
			t.Fatalf("%s is empty, so this guard checked nothing", path)
		}
		line, paragraph := zeroAdapterParagraph(t, document, path, "zero configured Adapters")
		if !strings.Contains(paragraph, "connect") && !strings.Contains(paragraph, "health") {
			t.Fatalf("%s:%d states that the Endpoint accepts zero configured Adapters without saying what it does afterwards, so a reader cannot tell whether the node stays observable", path, line)
		}
		if strings.Contains(paragraph, "reports Endpoint health") || strings.Contains(paragraph, "reports health") {
			healthStated = true
		}
	}
	if !healthStated {
		t.Fatalf("no lifecycle document states that a zero-Adapter Endpoint reports health, so the health half of this row is undocumented")
	}
}
