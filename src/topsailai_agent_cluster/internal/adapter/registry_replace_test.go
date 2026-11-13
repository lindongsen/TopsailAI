package adapter

import (
	"context"
	"sync"
	"testing"
)

// countingAdapter records how many times Close was called so a test can prove a
// retired instance is not closed while a caller still holds it.
type countingAdapter struct {
	testAdapter
	mu     sync.Mutex
	closes int
}

func (a *countingAdapter) Close() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.closes++
	return nil
}

func (a *countingAdapter) closeCount() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.closes
}

// replaceFixture builds a registry whose factory mints one distinct counting
// instance per Configure call, and records them in creation order.
//
// Distinct instances matter: a factory that returns one shared value would make
// every "unrelated adapter was not closed" assertion vacuous, because the second
// adapter would be the same object as the first.
type replaceFixture struct {
	registry  *Registry
	instances []*countingAdapter
}

func newReplaceFixture(t *testing.T) *replaceFixture {
	t.Helper()
	fixture := &replaceFixture{registry: NewRegistry()}
	if err := fixture.registry.RegisterType("fixture", func(context.Context, Config) (Adapter, error) {
		created := &countingAdapter{}
		fixture.instances = append(fixture.instances, created)
		return created, nil
	}); err != nil {
		t.Fatalf("register type: %v", err)
	}
	return fixture
}

// configure creates one adapter and returns the instance the factory minted.
func (f *replaceFixture) configure(t *testing.T, adapterID string) *countingAdapter {
	t.Helper()
	before := len(f.instances)
	if _, err := f.registry.Configure(context.Background(), Config{AdapterID: adapterID, ProviderType: "fixture"}); err != nil {
		t.Fatalf("configure %s: %v", adapterID, err)
	}
	if len(f.instances) != before+1 {
		t.Fatalf("factory did not mint one instance for %s", adapterID)
	}
	return f.instances[len(f.instances)-1]
}

// TestRegistryAcquireKeepsRetiredInstanceAliveUntilRelease proves the property that
// makes a Provider CLI version replacement safe: an instance that a caller already
// acquired is not closed by the replacement, and it is closed only when that caller
// releases.
func TestRegistryAcquireKeepsRetiredInstanceAliveUntilRelease(t *testing.T) {
	fixture := newReplaceFixture(t)
	previous := fixture.configure(t, "a")

	held, release, ok := fixture.registry.Acquire("a")
	if !ok {
		t.Fatal("acquire failed")
	}
	if held != previous {
		t.Fatal("acquire returned a different instance")
	}

	next := &countingAdapter{}
	if _, err := fixture.registry.Replace("a", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 0 {
		t.Fatalf("retired instance closed while still held: closes=%d", got)
	}
	if got := fixture.registry.InFlight("a"); got != 1 {
		t.Fatalf("in-flight count = %d, want 1", got)
	}

	release()
	if got := previous.closeCount(); got != 1 {
		t.Fatalf("retired instance close count = %d, want 1", got)
	}
	if got := fixture.registry.InFlight("a"); got != 0 {
		t.Fatalf("in-flight count after release = %d, want 0", got)
	}
	if got := next.closeCount(); got != 0 {
		t.Fatalf("active instance was closed: closes=%d", got)
	}
}

// TestRegistryReplaceClosesUnreferencedInstanceImmediately proves a replacement with
// no callers in flight does not leak the previous instance.
func TestRegistryReplaceClosesUnreferencedInstanceImmediately(t *testing.T) {
	fixture := newReplaceFixture(t)
	previous := fixture.configure(t, "a")

	next := &countingAdapter{}
	if _, err := fixture.registry.Replace("a", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 1 {
		t.Fatalf("previous close count = %d, want 1", got)
	}
	if got := fixture.registry.InFlight("a"); got != 0 {
		t.Fatalf("in-flight count = %d, want 0", got)
	}
	current, ok := fixture.registry.Get("a")
	if !ok || current != next {
		t.Fatal("registry does not expose the replacement")
	}
}

// TestRegistryReplaceRejectsUnknownAndIdenticalInstances proves a failed replacement
// changes nothing, which is what keeps the previous version serving traffic.
func TestRegistryReplaceRejectsUnknownAndIdenticalInstances(t *testing.T) {
	fixture := newReplaceFixture(t)
	previous := fixture.configure(t, "a")

	if _, err := fixture.registry.Replace("", &countingAdapter{}); err == nil {
		t.Fatal("empty adapter ID was accepted")
	}
	if _, err := fixture.registry.Replace("a", nil); err == nil {
		t.Fatal("nil replacement was accepted")
	}
	if _, err := fixture.registry.Replace("missing", &countingAdapter{}); err == nil {
		t.Fatal("unknown adapter ID was accepted")
	}
	if _, err := fixture.registry.Replace("a", previous); err == nil {
		t.Fatal("identical instance was accepted")
	}
	if got := previous.closeCount(); got != 0 {
		t.Fatalf("failed replacement closed the active instance: closes=%d", got)
	}
	current, ok := fixture.registry.Get("a")
	if !ok || current != previous {
		t.Fatal("failed replacement changed the active instance")
	}
}

// TestRegistryAcquireAllHoldsEveryInstance proves a bounded scan that consults every
// adapter keeps each instance alive across a replacement that lands mid-scan.
func TestRegistryAcquireAllHoldsEveryInstance(t *testing.T) {
	fixture := newReplaceFixture(t)
	first := fixture.configure(t, "a")
	second := fixture.configure(t, "b")
	if first == second {
		t.Fatal("fixture minted one shared instance for two adapters")
	}

	instances, release := fixture.registry.AcquireAll()
	if len(instances) != 2 {
		t.Fatalf("acquired %d instances, want 2", len(instances))
	}

	next := &countingAdapter{}
	if _, err := fixture.registry.Replace("a", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := first.closeCount(); got != 0 {
		t.Fatalf("instance closed during a held scan: closes=%d", got)
	}

	release()
	if got := first.closeCount(); got != 1 {
		t.Fatalf("first close count = %d, want 1", got)
	}
	if got := second.closeCount(); got != 0 {
		t.Fatalf("unrelated instance was closed: closes=%d", got)
	}
}

// TestRegistryAcquireReleaseIsIdempotent proves a caller can defer release without
// tracking whether it already ran, which is how every call site uses it.
func TestRegistryAcquireReleaseIsIdempotent(t *testing.T) {
	fixture := newReplaceFixture(t)
	previous := fixture.configure(t, "a")

	_, release, ok := fixture.registry.Acquire("a")
	if !ok {
		t.Fatal("acquire failed")
	}
	release()
	release()
	if got := fixture.registry.InFlight("a"); got != 0 {
		t.Fatalf("in-flight count = %d, want 0", got)
	}

	next := &countingAdapter{}
	if _, err := fixture.registry.Replace("a", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := previous.closeCount(); got != 1 {
		t.Fatalf("previous close count = %d, want 1", got)
	}
}

// TestRegistryReplaceDoesNotAffectOtherAdapters proves replacing one adapter leaves
// every other adapter on its own instance.
func TestRegistryReplaceDoesNotAffectOtherAdapters(t *testing.T) {
	fixture := newReplaceFixture(t)
	first := fixture.configure(t, "a")
	other := fixture.configure(t, "b")
	if first == other {
		t.Fatal("fixture minted one shared instance for two adapters")
	}

	next := &countingAdapter{}
	if _, err := fixture.registry.Replace("a", next); err != nil {
		t.Fatalf("replace: %v", err)
	}
	if got := first.closeCount(); got != 1 {
		t.Fatalf("replaced instance close count = %d, want 1", got)
	}
	if got := other.closeCount(); got != 0 {
		t.Fatalf("unrelated adapter was closed: closes=%d", got)
	}
	current, ok := fixture.registry.Get("b")
	if !ok || current != other {
		t.Fatal("unrelated adapter instance changed")
	}
}

// TestRegistryAcquireUnknownAdapterFails proves a caller cannot acquire an adapter
// that is not configured, so a replace cannot be reached through a typo.
func TestRegistryAcquireUnknownAdapterFails(t *testing.T) {
	fixture := newReplaceFixture(t)
	if _, release, ok := fixture.registry.Acquire("missing"); ok || release != nil {
		t.Fatal("acquire returned an unknown adapter")
	}
	if got := fixture.registry.InFlight("missing"); got != 0 {
		t.Fatalf("in-flight count for unknown adapter = %d, want 0", got)
	}
}
