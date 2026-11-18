package main

// The advertised capability revision is a Provider-decided seam: the Endpoint
// copies the Provider's `descriptor_revision` through unchanged. Three documents
// describe it, and none of them is parsed by code, so a sentence that reverts to
// the old story produces no failure anywhere. The old story was that the value
// came from the Adapter configuration, which is exactly the defect the seam
// replaced: an operator-written string that never changes while the served
// surface does.
//
// The guard therefore pins both directions. It refuses the sentences that state
// the removed behaviour, and it requires each document to state the Provider
// source. Requiring the positive statement is what stops a vacuous pass: deleting
// the paragraph would satisfy every negative check while leaving a reader with no
// description at all.
//
// The documents are read from disk rather than asserted through a function,
// because the regression is prose. No code path can observe a wrong sentence.

import (
	"strings"
	"testing"
)

// capabilityRevisionDocuments are the documents that describe the seam. The
// provider-facing README is included because a Provider author reads it to learn
// what the cluster publishes, and the adapters document is included because it
// owns the numbered Provider obligations.
var capabilityRevisionDocuments = []string{
	"docs/agent-cluster-protocol.md",
	"docs/agent-cluster-adapters.md",
	"protocol/provider-cli/v1/README.md",
}

// capabilityRevisionRemovedClaims are sentences that state the removed
// behaviour. Each one was present in a document and each one is false now: the
// value is not the Adapter configuration's, it is not copied from configuration,
// and the document seams are no longer the only Provider-decided seams.
var capabilityRevisionRemovedClaims = []string{
	"Adapter configuration's own `revision` value",
	"comes from configuration rather than from the descriptor",
	"seams in the protocol where the content is decided entirely by the Provider",
}

// capabilityRevisionRequiredClaims are the statements each document must carry.
// The key is the document; the value is the phrase that document must contain.
// The phrases differ because each document addresses a different reader: the
// protocol states the forwarding rule, the adapters document states the Provider
// obligation, and the provider README states what the Provider must declare.
var capabilityRevisionRequiredClaims = map[string]string{
	"docs/agent-cluster-protocol.md":     "### The capability revision seam",
	"docs/agent-cluster-adapters.md":     "Declare `descriptor_revision` in the `describe` result",
	"protocol/provider-cli/v1/README.md": "### The capability revision seam",
}

// capabilityRevisionProviderSource is the phrase every document must use to name
// where the value comes from. It is checked separately from the required claims
// so a document cannot satisfy the guard by naming the section while describing
// the wrong source inside it.
const capabilityRevisionProviderSource = "descriptor_revision"

// TestCapabilityRevisionDocumentsDoNotStateTheRemovedBehaviour refuses every
// sentence that describes the value as configuration-owned.
func TestCapabilityRevisionDocumentsDoNotStateTheRemovedBehaviour(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range capabilityRevisionDocuments {
		document := readRepoFile(t, root, relative)
		for _, claim := range capabilityRevisionRemovedClaims {
			if strings.Contains(document, claim) {
				t.Fatalf("%s still states %q, so it describes the removed configuration-owned revision", relative, claim)
			}
		}
	}
}

// TestCapabilityRevisionDocumentsNameTheProviderSource requires each document to
// describe the seam and to name the Provider field it forwards.
//
// The non-vacuity check is the section requirement: a document that dropped the
// paragraph entirely would pass the negative test above, so this test is what
// makes the pair meaningful.
func TestCapabilityRevisionDocumentsNameTheProviderSource(t *testing.T) {
	root := repoRoot(t)
	for _, relative := range capabilityRevisionDocuments {
		document := readRepoFile(t, root, relative)
		required, ok := capabilityRevisionRequiredClaims[relative]
		if !ok {
			t.Fatalf("%s is listed as a capability revision document but has no required claim, so this guard checked nothing for it", relative)
		}
		if !strings.Contains(document, required) {
			t.Fatalf("%s does not contain %q, so it does not describe the capability revision seam", relative, required)
		}
		if !strings.Contains(document, capabilityRevisionProviderSource) {
			t.Fatalf("%s does not name %q, so a reader cannot tell where the advertised revision comes from", relative, capabilityRevisionProviderSource)
		}
	}
}

// TestCapabilityRevisionSeamIsNotDescribedAsTheOnlyProviderSeam refuses the
// claim that the two document fields are the only Provider-decided seams.
//
// The capability revision is a third seam, so a sentence that counts the seams
// and stops at two is false. It is checked as an exact phrase rather than as a
// search for the words "only" and "seam", because other paragraphs legitimately
// describe a single seam: the identity table says a provider launch-profile key
// is resolved only inside the Endpoint/provider seam, and that sentence is true.
// A word-level check would refuse it and force the guard to be weakened.
func TestCapabilityRevisionSeamIsNotDescribedAsTheOnlyProviderSeam(t *testing.T) {
	root := repoRoot(t)
	// The phrase is matched with whitespace collapsed, because the sentence wraps
	// across lines and a line break must not hide it.
	const exclusivityClaim = "the only seams in the protocol"
	for _, relative := range capabilityRevisionDocuments {
		document := readRepoFile(t, root, relative)
		collapsed := strings.Join(strings.Fields(document), " ")
		if strings.Contains(collapsed, exclusivityClaim) {
			t.Fatalf("%s still claims %q, so it contradicts the capability revision seam", relative, exclusivityClaim)
		}
	}
}
