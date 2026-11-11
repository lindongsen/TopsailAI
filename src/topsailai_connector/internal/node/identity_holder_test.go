package node

import (
	"sync"
	"testing"

	"topsailai_connector/internal/security"
)

// holderFixture is a pair of identities a test can swap between.
type holderFixture struct {
	first  security.NodeIdentity
	second security.NodeIdentity
}

// newHolderFixture builds two distinct identities, so a test can tell which one a
// reader observed.
func newHolderFixture(t *testing.T) holderFixture {
	t.Helper()

	first, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	second, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	if first.ID == second.ID {
		t.Fatal("two generated identities share an identifier, so a test cannot tell them apart")
	}
	return holderFixture{first: first, second: second}
}

// TestIdentityHolderReturnsTheInitialValue checks that a holder reports the pair
// it was built with, because a Node that started with one identity must serve
// that identity until something replaces it.
func TestIdentityHolderReturnsTheInitialValue(t *testing.T) {
	fixture := newHolderFixture(t)

	holder := NewIdentityHolder(fixture.first)
	current := holder.Current()

	if current.ID != fixture.first.ID {
		t.Fatalf("Current().ID = %q, want %q", current.ID, fixture.first.ID)
	}
	if !current.Token.Equal(fixture.first.Token) {
		t.Fatal("Current().Token does not match the identity the holder was built with")
	}
}

// TestIdentityHolderReplaceReportsAChange checks that replacing the pair is
// visible to a reader and reported as a change, because the report is what drops
// the live channel.
func TestIdentityHolderReplaceReportsAChange(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.first)

	if !holder.Replace(fixture.second) {
		t.Fatal("Replace() = false, want true for a different pair")
	}
	if current := holder.Current(); current.ID != fixture.second.ID {
		t.Fatalf("Current().ID = %q, want %q after Replace", current.ID, fixture.second.ID)
	}
}

// TestIdentityHolderReplaceReportsNoChangeForTheSamePair checks that installing
// an identical pair is not reported as a change.
//
// The distinction matters: the watcher polls the file, and a rewrite that produced
// the same pair must not drop a working channel. A holder that reported every
// write as a change would turn an unrelated file touch into a reconnect.
func TestIdentityHolderReplaceReportsNoChangeForTheSamePair(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.first)

	if holder.Replace(fixture.first) {
		t.Fatal("Replace() = true, want false for the pair already held")
	}
}

// TestIdentityHolderReplaceDetectsATokenOnlyChange checks that a regeneration
// which keeps the identifier is still reported as a change.
//
// `regenerate --keep-id` is the common case, and it changes only the token. A
// holder that compared identifiers alone would report no change and the old token
// would keep working, which is the defect this whole mechanism exists to fix.
func TestIdentityHolderReplaceDetectsATokenOnlyChange(t *testing.T) {
	fixture := newHolderFixture(t)

	keptID, err := security.NewNodeToken(fixture.first.ID)
	if err != nil {
		t.Fatalf("NewNodeToken() = %v, want nil", err)
	}
	if keptID.ID != fixture.first.ID {
		t.Fatal("NewNodeToken() changed the identifier, so the test is not exercising a token-only change")
	}

	holder := NewIdentityHolder(fixture.first)
	if !holder.Replace(keptID) {
		t.Fatal("Replace() = false, want true when only the token changed")
	}
	if !holder.Current().Token.Equal(keptID.Token) {
		t.Fatal("Current().Token is not the replacement token")
	}
}

// TestIdentityHolderNilReturnsTheZeroIdentity checks that a nil holder answers
// instead of panicking.
//
// A dispatcher built without an identity must refuse every request rather than
// crash on the request path, and the zero identity matches no request, so the
// refusal is the default-deny answer the design requires.
func TestIdentityHolderNilReturnsTheZeroIdentity(t *testing.T) {
	var holder *IdentityHolder

	if current := holder.Current(); current.ID != "" || current.Token != "" {
		t.Fatalf("Current() = %q, want the zero identity for a nil holder", current.ID)
	}
	if holder.Replace(security.NodeIdentity{ID: "node_x", Token: security.Secret("y")}) {
		t.Fatal("Replace() = true on a nil holder, want false")
	}
}

// TestIdentityHolderIsSafeUnderConcurrentReadAndReplace checks that a reader and
// a writer can use the holder at the same time.
//
// The race detector is the assertion here: a plain field would be reported as a
// data race, and the test fails on that report rather than on a wrong value. The
// test also checks that every observed value is one of the two pairs, because a
// torn read would produce a mixture.
func TestIdentityHolderIsSafeUnderConcurrentReadAndReplace(t *testing.T) {
	fixture := newHolderFixture(t)
	holder := NewIdentityHolder(fixture.first)

	const iterations = 200
	var waitGroup sync.WaitGroup

	waitGroup.Add(1)
	go func() {
		defer waitGroup.Done()
		for index := 0; index < iterations; index++ {
			if index%2 == 0 {
				holder.Replace(fixture.second)
				continue
			}
			holder.Replace(fixture.first)
		}
	}()

	waitGroup.Add(1)
	go func() {
		defer waitGroup.Done()
		for index := 0; index < iterations; index++ {
			current := holder.Current()
			if current.ID != fixture.first.ID && current.ID != fixture.second.ID {
				t.Errorf("Current().ID = %q, want one of the two fixture identifiers", current.ID)
				return
			}
		}
	}()

	waitGroup.Wait()
}
