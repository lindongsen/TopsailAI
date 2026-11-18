package node

import (
	"sync"
	"testing"

	"topsailai_connector/internal/security"
)

// holderFixture is a pair of node ids and credential sets a test can swap between.
type holderFixture struct {
	firstID    string
	secondID   string
	firstSet   *security.CredentialSet
	secondSet  *security.CredentialSet
	firstCred  security.Credential
	secondCred security.Credential
}

// newHolderFixture builds two distinct node ids and two distinct credential sets, so
// a test can tell which one a reader observed.
func newHolderFixture(t *testing.T) holderFixture {
	t.Helper()

	firstID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	secondID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	if firstID == secondID {
		t.Fatal("two generated node ids share a value, so a test cannot tell them apart")
	}

	firstCred, err := security.NewCredentialWithKeyID("first-caller")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v, want nil", err)
	}
	secondCred, err := security.NewCredentialWithKeyID("second-caller")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v, want nil", err)
	}

	firstSet, err := security.NewCredentialSet([]security.Credential{firstCred})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v, want nil", err)
	}
	secondSet, err := security.NewCredentialSet([]security.Credential{secondCred})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v, want nil", err)
	}

	return holderFixture{
		firstID:    firstID,
		secondID:   secondID,
		firstSet:   firstSet,
		secondSet:  secondSet,
		firstCred:  firstCred,
		secondCred: secondCred,
	}
}

// TestIdentityHolderReturnsTheInitialValue checks that a holder reports the node id
// and credential set it was built with, because a Node that started with one identity
// must serve that identity until something replaces it.
func TestIdentityHolderReturnsTheInitialValue(t *testing.T) {
	fixture := newHolderFixture(t)

	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	if got := holder.NodeID(); got != fixture.firstID {
		t.Fatalf("NodeID() = %q, want %q", got, fixture.firstID)
	}
	if _, present := holder.Credentials().Lookup(fixture.firstCred.KeyID); !present {
		t.Fatal("Credentials() does not hold the credential the holder was built with")
	}
}

// TestIdentityHolderReplaceNodeIDReportsAChange checks that replacing the node id is
// visible to a reader and reported as a change, because the report is what drops the
// live channel.
func TestIdentityHolderReplaceNodeIDReportsAChange(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	if !holder.ReplaceNodeID(fixture.secondID) {
		t.Fatal("ReplaceNodeID() = false, want true for a different id")
	}
	if got := holder.NodeID(); got != fixture.secondID {
		t.Fatalf("NodeID() = %q, want %q after ReplaceNodeID", got, fixture.secondID)
	}
}

// TestIdentityHolderReplaceNodeIDReportsNoChangeForTheSameValue checks that installing
// an identical node id is not reported as a change.
//
// The distinction matters: the watcher polls the file, and a rewrite that produced the
// same value must not drop a working channel.
func TestIdentityHolderReplaceNodeIDReportsNoChangeForTheSameValue(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	if holder.ReplaceNodeID(fixture.firstID) {
		t.Fatal("ReplaceNodeID() = true, want false for the id already held")
	}
}

// TestIdentityHolderReplaceCredentialsReportsAChange checks that a credential set with
// a different key identifier is adopted.
//
// Revoking a caller must take effect on a running Node, otherwise the operator would
// have to restart the process to make a revocation real.
func TestIdentityHolderReplaceCredentialsReportsAChange(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	if !holder.ReplaceCredentials(fixture.secondSet) {
		t.Fatal("ReplaceCredentials() = false, want true for a different key id set")
	}
	if _, present := holder.Credentials().Lookup(fixture.secondCred.KeyID); !present {
		t.Fatal("Credentials() does not hold the replacement credential")
	}
	if _, present := holder.Credentials().Lookup(fixture.firstCred.KeyID); present {
		t.Fatal("Credentials() still holds the revoked credential")
	}
}

// TestIdentityHolderReplaceCredentialsReportsNoChangeForTheSameKeyIDs checks that a
// set naming the same key identifiers is not reported as a change.
//
// A set deliberately exposes no way to read a secret back, so a secret rotation under
// one identifier is invisible to this comparison. That is the correct answer for the
// caller: the channel was authenticated with the identifier, and a secret rotation
// under one identifier is a change the operator makes by restarting the Node.
func TestIdentityHolderReplaceCredentialsReportsNoChangeForTheSameKeyIDs(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	rotated, err := security.NewCredentialWithKeyID(fixture.firstCred.KeyID)
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v, want nil", err)
	}
	rotatedSet, err := security.NewCredentialSet([]security.Credential{rotated})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v, want nil", err)
	}

	if holder.ReplaceCredentials(rotatedSet) {
		t.Fatal("ReplaceCredentials() = true, want false when only the secret changed")
	}
}

// TestIdentityHolderNilReturnsTheZeroValue checks that a nil holder answers instead of
// panicking.
//
// A dispatcher built without an identity must refuse every request rather than crash
// on the request path, and the empty identifier matches no request, so the refusal is
// the default-deny answer the design requires.
func TestIdentityHolderNilReturnsTheZeroValue(t *testing.T) {
	var holder *IdentityHolder

	if got := holder.NodeID(); got != "" {
		t.Fatalf("NodeID() = %q, want an empty id for a nil holder", got)
	}
	if holder.Credentials() != nil {
		t.Fatal("Credentials() = a set for a nil holder, want nil")
	}
	if holder.ReplaceNodeID("node_x") {
		t.Fatal("ReplaceNodeID() = true on a nil holder, want false")
	}
	if holder.ReplaceCredentials(nil) {
		t.Fatal("ReplaceCredentials() = true on a nil holder, want false")
	}
}

// TestIdentityHolderIsSafeUnderConcurrentReadAndReplace checks that a reader and a
// writer can use the holder at the same time.
//
// The race detector is the assertion here: a plain field would be reported as a data
// race, and the test fails on that report rather than on a wrong value. The test also
// checks that every observed value is one of the two fixture values, because a torn
// read would produce a mixture.
func TestIdentityHolderIsSafeUnderConcurrentReadAndReplace(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.firstID, fixture.firstSet)

	const iterations = 200
	var waitGroup sync.WaitGroup

	waitGroup.Add(1)
	go func() {
		defer waitGroup.Done()
		for index := 0; index < iterations; index++ {
			if index%2 == 0 {
				holder.ReplaceNodeID(fixture.secondID)
				holder.ReplaceCredentials(fixture.secondSet)
				continue
			}
			holder.ReplaceNodeID(fixture.firstID)
			holder.ReplaceCredentials(fixture.firstSet)
		}
	}()

	waitGroup.Add(1)
	go func() {
		defer waitGroup.Done()
		for index := 0; index < iterations; index++ {
			current := holder.NodeID()
			if current != fixture.firstID && current != fixture.secondID {
				t.Errorf("NodeID() = %q, want one of the two fixture identifiers", current)
				return
			}
			if holder.Credentials() == nil {
				t.Errorf("Credentials() = nil, want a set")
				return
			}
		}
	}()

	waitGroup.Wait()
}
