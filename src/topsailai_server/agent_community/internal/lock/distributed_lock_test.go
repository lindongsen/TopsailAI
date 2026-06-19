package lock

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats-server/v2/test"
	"github.com/nats-io/nats.go"
)

const testBucketName = "acs_test_locks"

// setShortTimeouts overrides the package-level renewal and release timeouts
// with small values suitable for fast unit tests. It returns a function that
// restores the original values.
func setShortTimeouts(t *testing.T) func() {
	t.Helper()
	origRenewal := renewalInterval
	origRelease := releaseWait
	renewalInterval = 200 * time.Millisecond
	releaseWait = 500 * time.Millisecond
	return func() {
		renewalInterval = origRenewal
		releaseWait = origRelease
	}
}

// startNATSServer starts an in-process NATS server with JetStream enabled and
// returns the server and a cleanup function.
func startNATSServer(t *testing.T) (*server.Server, func()) {
	t.Helper()

	opts := test.DefaultTestOptions
	opts.Port = -1
	opts.JetStream = true
	opts.StoreDir = t.TempDir()

	s := test.RunServer(&opts)
	if s == nil {
		t.Fatal("failed to start NATS test server")
	}

	return s, func() {
		s.Shutdown()
		s.WaitForShutdown()
	}
}

// connectJS connects to the test server and returns a JetStream context.
func connectJS(t *testing.T, s *server.Server) nats.JetStreamContext {
	t.Helper()

	nc, err := nats.Connect(s.ClientURL())
	if err != nil {
		t.Fatalf("failed to connect to NATS: %v", err)
	}
	t.Cleanup(func() { nc.Close() })

	js, err := nc.JetStream()
	if err != nil {
		t.Fatalf("failed to create JetStream context: %v", err)
	}
	return js
}

// newTestLock creates a DistributedLock for testing.
func newTestLock(t *testing.T, js nats.JetStreamContext) *DistributedLock {
	t.Helper()

	dl, err := NewDistributedLock(js, testBucketName)
	if err != nil {
		t.Fatalf("failed to create distributed lock: %v", err)
	}
	return dl
}

func TestAcquireAndRelease(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-1")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	held, err := lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld failed: %v", err)
	}
	if !held {
		t.Fatal("expected lock to be held")
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}

	held, err = lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld after release failed: %v", err)
	}
	if held {
		t.Fatal("expected lock to not be held after release")
	}
}

func TestAcquireAlreadyHeld(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock1, err := dl.Acquire(context.Background(), "test", "resource-2")
	if err != nil {
		t.Fatalf("first Acquire failed: %v", err)
	}
	defer lock1.Release()

	_, err = dl.Acquire(context.Background(), "test", "resource-2")
	if !errors.Is(err, ErrLockHeld) {
		t.Fatalf("expected ErrLockHeld, got: %v", err)
	}
}

func TestFencingToken(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-3")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	if lock.FencingToken() == "" {
		t.Fatal("expected non-empty fencing token")
	}

	held, err := lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld failed: %v", err)
	}
	if !held {
		t.Fatal("expected lock to be held with matching token")
	}

	// Simulate another owner taking the lock by overwriting the value.
	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	if _, err := lock.kv.Put(key, []byte("other-token")); err != nil {
		t.Fatalf("failed to overwrite lock value: %v", err)
	}

	held, err = lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld after token change failed: %v", err)
	}
	if held {
		t.Fatal("expected lock to not be held after token changed")
	}

	select {
	case <-lock.Lost():
		// expected
	case <-time.After(2 * time.Second):
		t.Fatal("expected Lost() channel to be closed after token mismatch")
	}
}

func TestRenewalKeepsLockAlive(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)

	// Use a short TTL bucket to verify renewal works. The renewal interval is
	// overridden to 200ms by setShortTimeouts, so we use a TTL just long enough
	// to require at least one renewal during the sleep.
	shortTTL := 500 * time.Millisecond
	_, err := js.CreateKeyValue(&nats.KeyValueConfig{
		Bucket: "acs_test_locks_short_ttl",
		TTL:    shortTTL,
	})
	if err != nil {
		t.Fatalf("failed to create short TTL bucket: %v", err)
	}

	dlShort, err := NewDistributedLock(js, "acs_test_locks_short_ttl")
	if err != nil {
		t.Fatalf("failed to create short TTL lock manager: %v", err)
	}

	lock, err := dlShort.Acquire(context.Background(), "test", "resource-renew")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	// Wait longer than the TTL; if renewal works, the lock remains held.
	time.Sleep(3 * shortTTL)

	held, err := lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld failed: %v", err)
	}
	if !held {
		t.Fatal("expected lock to still be held after TTL boundary")
	}
}

func TestLostChannelNotClosedOnNormalRelease(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-4")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	if err := lock.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}

	select {
	case <-lock.Lost():
		t.Fatal("Lost() channel should not be closed on normal Release()")
	case <-time.After(200 * time.Millisecond):
		// expected
	}
}

func TestLostChannelClosedOnUnexpectedLoss(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-5")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	// Force the lock to be lost by deleting the key.
	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	if err := lock.kv.Delete(key); err != nil {
		t.Fatalf("failed to delete lock key: %v", err)
	}

	// Wait for the renewal loop to detect the loss.
	select {
	case <-lock.Lost():
		// expected
	case <-time.After(2 * time.Second):
		t.Fatal("expected Lost() channel to be closed after key deletion")
	}
}

func TestConcurrentBucketCreationRace(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)

	// Pre-create the bucket to simulate another ACS instance winning the race.
	_, err := js.CreateKeyValue(&nats.KeyValueConfig{
		Bucket: testBucketName,
		TTL:    lockTTL,
	})
	if err != nil {
		t.Fatalf("failed to pre-create bucket: %v", err)
	}

	// NewDistributedLock should succeed by re-fetching the existing bucket.
	dl, err := NewDistributedLock(js, testBucketName)
	if err != nil {
		t.Fatalf("NewDistributedLock failed when bucket already exists: %v", err)
	}

	lock, err := dl.Acquire(context.Background(), "test", "resource-race")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("Release failed: %v", err)
	}
}

func TestReleaseTimeoutDoesNotBlock(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-timeout")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	// Replace the kv with a wrapper that blocks Update operations to simulate a
	// stuck renewal goroutine. Release's own Get calls must remain unblocked so
	// that the timeout path can complete.
	blocker := &blockingKV{kv: lock.kv, blockUpdateAfter: 0}
	lock.kv = blocker

	start := time.Now()
	err = lock.Release()
	elapsed := time.Since(start)

	if elapsed > releaseWait+500*time.Millisecond {
		t.Fatalf("Release blocked too long: %v", elapsed)
	}

	// Release should report a timeout warning via logs and may return an error
	// from the best-effort delete path. We accept either nil or non-nil error
	// as long as it did not block indefinitely.
	_ = err
}

func TestReleaseTOCTOUSafety(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-toctou")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	// Replace kv with a wrapper that changes the token between the two Get
	// calls inside Release.
	toctou := &toctouKV{kv: lock.kv, newToken: "stolen-token"}
	lock.kv = toctou

	err = lock.Release()
	if err == nil {
		t.Fatal("expected Release to return an error when token changed before delete")
	}

	// Verify the key still exists and is owned by the new token.
	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	entry, err := toctou.kv.Get(key)
	if err != nil {
		t.Fatalf("failed to get lock entry after release: %v", err)
	}
	if string(entry.Value()) != "stolen-token" {
		t.Fatalf("expected lock to remain with new token, got %q", string(entry.Value()))
	}
}

func TestIsHeldAfterKeyDisappears(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-gone")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	if err := lock.kv.Delete(key); err != nil {
		t.Fatalf("failed to delete lock key: %v", err)
	}

	held, err := lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld failed: %v", err)
	}
	if held {
		t.Fatal("expected lock to not be held after key deletion")
	}
}

func TestMultipleConcurrentAcquires(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	const numGoroutines = 10
	var wg sync.WaitGroup
	acquired := make(chan *Lock, 1)

	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			lock, err := dl.Acquire(context.Background(), "test", "resource-concurrent")
			if err == nil {
				select {
				case acquired <- lock:
					// we won
				default:
					// someone else already won; release ours
					_ = lock.Release()
				}
			} else if !errors.Is(err, ErrLockHeld) {
				t.Errorf("unexpected acquire error: %v", err)
			}
		}()
	}
	wg.Wait()
	close(acquired)

	winner := <-acquired
	if winner == nil {
		t.Fatal("expected exactly one goroutine to acquire the lock")
	}
	if err := winner.Release(); err != nil {
		t.Fatalf("Release winner failed: %v", err)
	}
}

// blockingKV blocks Update operations after a configurable number of calls.
// Get calls are intentionally left unblocked so that Release can still read
// the lock entry and complete its timeout path.
type blockingKV struct {
	kv               nats.KeyValue
	blockUpdateAfter int
	mu               sync.Mutex
	updateCalls      int
}

func (b *blockingKV) Get(key string) (nats.KeyValueEntry, error) {
	return b.kv.Get(key)
}

func (b *blockingKV) Create(key string, value []byte) (uint64, error) {
	return b.kv.Create(key, value)
}

func (b *blockingKV) Update(key string, value []byte, last uint64) (uint64, error) {
	b.mu.Lock()
	b.updateCalls++
	shouldBlock := b.updateCalls > b.blockUpdateAfter
	b.mu.Unlock()
	if shouldBlock {
		<-make(chan struct{}) // block forever
	}
	return b.kv.Update(key, value, last)
}

func (b *blockingKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return b.kv.Delete(key, opts...)
}

func (b *blockingKV) Put(key string, value []byte) (uint64, error) {
	return b.kv.Put(key, value)
}

func (b *blockingKV) PutString(key string, value string) (uint64, error) {
	return b.kv.PutString(key, value)
}

func (b *blockingKV) GetRevision(key string, revision uint64) (nats.KeyValueEntry, error) {
	return b.kv.GetRevision(key, revision)
}

func (b *blockingKV) Purge(key string, opts ...nats.DeleteOpt) error {
	return b.kv.Purge(key, opts...)
}

func (b *blockingKV) Watch(keys string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return b.kv.Watch(keys, opts...)
}

func (b *blockingKV) WatchAll(opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return b.kv.WatchAll(opts...)
}

func (b *blockingKV) WatchFiltered(keys []string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return b.kv.WatchFiltered(keys, opts...)
}

func (b *blockingKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return b.kv.Keys(opts...)
}

func (b *blockingKV) ListKeys(opts ...nats.WatchOpt) (nats.KeyLister, error) {
	return b.kv.ListKeys(opts...)
}

func (b *blockingKV) History(key string, opts ...nats.WatchOpt) ([]nats.KeyValueEntry, error) {
	return b.kv.History(key, opts...)
}

func (b *blockingKV) Bucket() string {
	return b.kv.Bucket()
}

func (b *blockingKV) PurgeDeletes(opts ...nats.PurgeOpt) error {
	return b.kv.PurgeDeletes(opts...)
}

func (b *blockingKV) Status() (nats.KeyValueStatus, error) {
	return b.kv.Status()
}

// toctouKV simulates another owner acquiring the lock between the two Get
// calls inside Release.
type toctouKV struct {
	kv       nats.KeyValue
	newToken string
	getCount int
	mu       sync.Mutex
}

func (t *toctouKV) Get(key string) (nats.KeyValueEntry, error) {
	t.mu.Lock()
	t.getCount++
	count := t.getCount
	t.mu.Unlock()

	entry, err := t.kv.Get(key)
	if err != nil {
		return nil, err
	}

	if count == 2 {
		// On the second Get (right before Delete), simulate another owner.
		rev, err := t.kv.Put(key, []byte(t.newToken))
		if err != nil {
			return nil, err
		}
		return &fakeEntry{bucket: t.kv.Bucket(), value: []byte(t.newToken), revision: rev}, nil
	}

	return entry, nil
}

func (t *toctouKV) Create(key string, value []byte) (uint64, error) {
	return t.kv.Create(key, value)
}

func (t *toctouKV) Update(key string, value []byte, last uint64) (uint64, error) {
	return t.kv.Update(key, value, last)
}

func (t *toctouKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return t.kv.Delete(key, opts...)
}

func (t *toctouKV) Put(key string, value []byte) (uint64, error) {
	return t.kv.Put(key, value)
}

func (t *toctouKV) PutString(key string, value string) (uint64, error) {
	return t.kv.PutString(key, value)
}

func (t *toctouKV) GetRevision(key string, revision uint64) (nats.KeyValueEntry, error) {
	return t.kv.GetRevision(key, revision)
}

func (t *toctouKV) Purge(key string, opts ...nats.DeleteOpt) error {
	return t.kv.Purge(key, opts...)
}

func (t *toctouKV) Watch(keys string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return t.kv.Watch(keys, opts...)
}

func (t *toctouKV) WatchAll(opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return t.kv.WatchAll(opts...)
}

func (t *toctouKV) WatchFiltered(keys []string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return t.kv.WatchFiltered(keys, opts...)
}

func (t *toctouKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return t.kv.Keys(opts...)
}

func (t *toctouKV) ListKeys(opts ...nats.WatchOpt) (nats.KeyLister, error) {
	return t.kv.ListKeys(opts...)
}

func (t *toctouKV) History(key string, opts ...nats.WatchOpt) ([]nats.KeyValueEntry, error) {
	return t.kv.History(key, opts...)
}

func (t *toctouKV) Bucket() string {
	return t.kv.Bucket()
}

func (t *toctouKV) PurgeDeletes(opts ...nats.PurgeOpt) error {
	return t.kv.PurgeDeletes(opts...)
}

func (t *toctouKV) Status() (nats.KeyValueStatus, error) {
	return t.kv.Status()
}

type fakeEntry struct {
	bucket   string
	value    []byte
	revision uint64
}

func (f *fakeEntry) Bucket() string            { return f.bucket }
func (f *fakeEntry) Key() string               { return "" }
func (f *fakeEntry) Value() []byte             { return f.value }
func (f *fakeEntry) Revision() uint64          { return f.revision }
func (f *fakeEntry) Created() time.Time        { return time.Now() }
func (f *fakeEntry) Delta() uint64             { return 0 }
func (f *fakeEntry) Operation() nats.KeyValueOp { return nats.KeyValuePut }

// TestRenewalUpdateInFlightDuringRelease verifies that if the renewal
// goroutine is inside kv.Update() when Release() is called, the lock is still
// deleted and is not accidentally re-created by the late Update.
func TestRenewalUpdateInFlightDuringRelease(t *testing.T) {
	restore := setShortTimeouts(t)
	defer restore()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)

	// Wrap JetStream so that the gating KV is used from the start. This avoids
	// mutating lock.kv after Acquire, which would race with the renewal goroutine.
	gate := make(chan struct{})
	var closeGateOnce sync.Once
	gjs := &gatingJetStream{
		JetStreamContext: js,
		bucketName:       testBucketName,
		gate:             gate,
	}

	dl, err := NewDistributedLock(gjs, testBucketName)
	if err != nil {
		t.Fatalf("failed to create distributed lock: %v", err)
	}

	var lock *Lock
	lock, err = dl.Acquire(context.Background(), "test", "resource-release-renew-race")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	// Ensure the renewal goroutine always exits before the test returns and
	// before the deferred timeout restore runs.
	defer func() {
		closeGateOnce.Do(func() { close(gate) })
		lock.renewWg.Wait()
	}()

	// Wait until the renewal goroutine is blocked inside Update.
	select {
	case <-gate:
		// The wrapper has signaled it is inside Update.
	case <-time.After(2 * time.Second):
		t.Fatal("renewal goroutine did not enter Update in time")
	}

	// Release while the renewal Update is blocked. Because the wrapper's
	// Update is blocked, Release's Get calls will see the original token and
	// proceed to delete the key.
	releaseDone := make(chan error, 1)
	go func() {
		releaseDone <- lock.Release()
	}()

	// Give Release time to delete the key before unblocking the late Update.
	time.Sleep(100 * time.Millisecond)

	// Unblock the renewal goroutine. Its Update should now fail (key gone or
	// revision mismatch), not recreate the lock.
	closeGateOnce.Do(func() { close(gate) })

	select {
	case err := <-releaseDone:
		if err != nil {
			t.Fatalf("Release returned unexpected error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Release did not complete in time")
	}

	// The lock key must not exist anymore. Use the underlying JetStream KV
	// directly so we do not spawn another renewal goroutine.
	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	rawKV, err := js.KeyValue(testBucketName)
	if err != nil {
		t.Fatalf("failed to get underlying kv: %v", err)
	}
	if _, err := rawKV.Get(key); err != nats.ErrKeyNotFound {
		t.Fatalf("expected key to be deleted, got err=%v", err)
	}
}

// TestTokenMismatchDuringRenewal verifies that if another owner overwrites the
// lock value, the original holder's renewal loop detects the token mismatch,
// marks the lock as lost, and stops renewing.
func TestTokenMismatchDuringRenewal(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-token-mismatch")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}
	defer lock.Release()

	// Simulate another owner taking the lock by overwriting the value.
	key := fmt.Sprintf(lockKeyFormat, lock.LockType(), lock.ResourceID())
	if _, err := lock.kv.Put(key, []byte("other-owner-token")); err != nil {
		t.Fatalf("failed to overwrite lock value: %v", err)
	}

	// Wait for the renewal loop to detect the mismatch and close Lost().
	select {
	case <-lock.Lost():
		// expected
	case <-time.After(2 * time.Second):
		t.Fatal("expected Lost() channel to be closed after token mismatch")
	}

	held, err := lock.IsHeld()
	if err != nil {
		t.Fatalf("IsHeld failed: %v", err)
	}
	if held {
		t.Fatal("expected lock to not be held after token mismatch")
	}
}

// TestConcurrentNewDistributedLock verifies that multiple goroutines calling
// NewDistributedLock concurrently with the same bucket name all succeed and do
// not leave inconsistent state.
func TestConcurrentNewDistributedLock(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)

	const numGoroutines = 10
	var wg sync.WaitGroup
	errs := make(chan error, numGoroutines)
	locks := make(chan *DistributedLock, numGoroutines)

	for i := 0; i < numGoroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			dl, err := NewDistributedLock(js, "acs_test_locks_race_bucket")
			if err != nil {
				errs <- err
				return
			}
			locks <- dl
		}()
	}
	wg.Wait()
	close(errs)
	close(locks)

	for err := range errs {
		t.Fatalf("NewDistributedLock failed in race: %v", err)
	}

	// All instances should be usable.
	var usable int
	for dl := range locks {
		lock, err := dl.Acquire(context.Background(), "test", fmt.Sprintf("resource-%d", usable))
		if err != nil {
			t.Fatalf("Acquire failed after race creation: %v", err)
		}
		if err := lock.Release(); err != nil {
			t.Fatalf("Release failed after race creation: %v", err)
		}
		usable++
	}
	if usable != numGoroutines {
		t.Fatalf("expected %d usable lock managers, got %d", numGoroutines, usable)
	}
}

// gatingJetStream wraps a JetStream context so that KeyValue(bucketName)
// returns an updateGatingKV. This lets tests inject the gate before Acquire
// starts the renewal goroutine, avoiding a race on lock.kv.
type gatingJetStream struct {
	nats.JetStreamContext
	bucketName string
	gate       chan struct{}
}

func (g *gatingJetStream) KeyValue(bucket string) (nats.KeyValue, error) {
	kv, err := g.JetStreamContext.KeyValue(bucket)
	if err != nil {
		return nil, err
	}
	if bucket == g.bucketName {
		return &updateGatingKV{kv: kv, gate: g.gate}, nil
	}
	return kv, nil
}

// updateGatingKV blocks the first Update call until the gate is closed, then
// forwards to the underlying KV. It signals when it has entered Update so tests
// can coordinate Release with an in-flight renewal.
type updateGatingKV struct {
	kv   nats.KeyValue
	gate chan struct{}
	once sync.Once
}

func (g *updateGatingKV) Get(key string) (nats.KeyValueEntry, error) {
	return g.kv.Get(key)
}

func (g *updateGatingKV) Create(key string, value []byte) (uint64, error) {
	return g.kv.Create(key, value)
}

func (g *updateGatingKV) Update(key string, value []byte, last uint64) (uint64, error) {
	g.once.Do(func() {
		// Signal that we are inside Update, then wait for the gate.
		g.gate <- struct{}{}
		<-g.gate
	})
	return g.kv.Update(key, value, last)
}

func (g *updateGatingKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return g.kv.Delete(key, opts...)
}

func (g *updateGatingKV) Put(key string, value []byte) (uint64, error) {
	return g.kv.Put(key, value)
}

func (g *updateGatingKV) PutString(key string, value string) (uint64, error) {
	return g.kv.PutString(key, value)
}

func (g *updateGatingKV) GetRevision(key string, revision uint64) (nats.KeyValueEntry, error) {
	return g.kv.GetRevision(key, revision)
}

func (g *updateGatingKV) Purge(key string, opts ...nats.DeleteOpt) error {
	return g.kv.Purge(key, opts...)
}

func (g *updateGatingKV) Watch(keys string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return g.kv.Watch(keys, opts...)
}

func (g *updateGatingKV) WatchAll(opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return g.kv.WatchAll(opts...)
}

func (g *updateGatingKV) WatchFiltered(keys []string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return g.kv.WatchFiltered(keys, opts...)
}

func (g *updateGatingKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return g.kv.Keys(opts...)
}

func (g *updateGatingKV) ListKeys(opts ...nats.WatchOpt) (nats.KeyLister, error) {
	return g.kv.ListKeys(opts...)
}

func (g *updateGatingKV) History(key string, opts ...nats.WatchOpt) ([]nats.KeyValueEntry, error) {
	return g.kv.History(key, opts...)
}

func (g *updateGatingKV) Bucket() string {
	return g.kv.Bucket()
}

func (g *updateGatingKV) PurgeDeletes(opts ...nats.PurgeOpt) error {
	return g.kv.PurgeDeletes(opts...)
}

func (g *updateGatingKV) Status() (nats.KeyValueStatus, error) {
	return g.kv.Status()
}

// errJetStream is a JetStream stub that returns configurable errors for
// KeyValue and CreateKeyValue. It is used to exercise NewDistributedLock and
// Acquire error paths without a real NATS server.
type errJetStream struct {
	nats.JetStreamContext
	keyValueErr error
	createErr   error
}

func (e *errJetStream) KeyValue(bucket string) (nats.KeyValue, error) {
	return nil, e.keyValueErr
}

func (e *errJetStream) CreateKeyValue(cfg *nats.KeyValueConfig) (nats.KeyValue, error) {
	return nil, e.createErr
}

// fixedKVJetStream always returns the configured KeyValue, ignoring the bucket.
type fixedKVJetStream struct {
	nats.JetStreamContext
	kv nats.KeyValue
}

func (f *fixedKVJetStream) KeyValue(bucket string) (nats.KeyValue, error) {
	return f.kv, nil
}

// raceReFetchJetStream simulates the bucket-create race where CreateKeyValue
// returns ErrStreamNameAlreadyInUse but the subsequent re-fetch fails.
type raceReFetchJetStream struct {
	nats.JetStreamContext
	keyValueErr    error
	keyValueCall   int
}

func (r *raceReFetchJetStream) KeyValue(bucket string) (nats.KeyValue, error) {
	r.keyValueCall++
	if r.keyValueCall == 1 {
		return nil, nats.ErrBucketNotFound
	}
	return nil, r.keyValueErr
}

func (r *raceReFetchJetStream) CreateKeyValue(cfg *nats.KeyValueConfig) (nats.KeyValue, error) {
	return nil, nats.ErrStreamNameAlreadyInUse
}

// failingKV is a KeyValue stub that returns configured errors for Get, Create
// and Delete. All other methods are not expected to be called.
type failingKV struct {
	nats.KeyValue
	getErr    error
	createErr error
	deleteErr error
}

func (f *failingKV) Get(key string) (nats.KeyValueEntry, error) {
	return nil, f.getErr
}

func (f *failingKV) Create(key string, value []byte) (uint64, error) {
	return 0, f.createErr
}

func (f *failingKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return f.deleteErr
}

// countingFailingKV counts how many times Get is called and always returns an
// error. It is used to verify that renew keeps retrying on transient Get errors.
type countingFailingKV struct {
	nats.KeyValue
	mu       sync.Mutex
	getCount int
}

func (c *countingFailingKV) Get(key string) (nats.KeyValueEntry, error) {
	c.mu.Lock()
	c.getCount++
	c.mu.Unlock()
	return nil, errors.New("repeated get error")
}

// wrongSeqError implements nats.JetStreamError with the wrong-last-sequence
// error code so that isWrongLastSequence returns true.
type wrongSeqError struct{}

func (e *wrongSeqError) Error() string { return "wrong last sequence" }

func (e *wrongSeqError) APIError() *nats.APIError {
	return &nats.APIError{ErrorCode: nats.JSErrCodeStreamWrongLastSequence}
}

// wrongSequenceKV returns a matching token on Get and a wrong-last-sequence
// error on Update.
type wrongSequenceKV struct {
	nats.KeyValue
	token string
}

func (w *wrongSequenceKV) Get(key string) (nats.KeyValueEntry, error) {
	return &fakeEntry{bucket: "test", value: []byte(w.token), revision: 1}, nil
}

func (w *wrongSequenceKV) Update(key string, value []byte, last uint64) (uint64, error) {
	return 0, &wrongSeqError{}
}

// tokenMismatchKV always returns a different token on Get.
type tokenMismatchKV struct {
	nats.KeyValue
	actualToken string
}

func (tm *tokenMismatchKV) Get(key string) (nats.KeyValueEntry, error) {
	return &fakeEntry{bucket: "test", value: []byte(tm.actualToken), revision: 1}, nil
}

// deleteFailureKV returns a matching token on Get and fails on Delete.
type deleteFailureKV struct {
	nats.KeyValue
	token     string
	deleteErr error
}

func (d *deleteFailureKV) Get(key string) (nats.KeyValueEntry, error) {
	return &fakeEntry{bucket: "test", value: []byte(d.token), revision: 1}, nil
}

func (d *deleteFailureKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return d.deleteErr
}

func TestNewDistributedLock_NilJetStream(t *testing.T) {
	_, err := NewDistributedLock(nil, testBucketName)
	if err == nil {
		t.Fatal("expected error when JetStream context is nil")
	}
	if err.Error() != "jetstream context is nil" {
		t.Fatalf("unexpected error message: %v", err)
	}
}

func TestNewDistributedLock_CreateOtherError(t *testing.T) {
	js := &errJetStream{
		keyValueErr: nats.ErrBucketNotFound,
		createErr:   errors.New("create failed"),
	}
	_, err := NewDistributedLock(js, testBucketName)
	if err == nil {
		t.Fatal("expected error when CreateKeyValue fails")
	}
	want := "failed to ensure lock bucket: failed to create kv bucket: create failed"
	if err.Error() != want {
		t.Fatalf("expected error %q, got %q", want, err.Error())
	}
}

func TestNewDistributedLock_RaceReFetchFails(t *testing.T) {
	js := &raceReFetchJetStream{
		keyValueErr: errors.New("re-fetch failed"),
	}
	_, err := NewDistributedLock(js, testBucketName)
	if err == nil {
		t.Fatal("expected error when bucket race re-fetch fails")
	}
	if !errors.Is(err, nats.ErrStreamNameAlreadyInUse) {
		t.Fatalf("expected error to wrap ErrStreamNameAlreadyInUse, got %v", err)
	}
}

func TestAcquire_InvalidKeyParts(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	_, err := dl.Acquire(context.Background(), "", "resource")
	if err == nil {
		t.Fatal("expected error for empty lockType")
	}
	want := "invalid lock type: lockType must not be empty"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}

	_, err = dl.Acquire(context.Background(), "type", "res.ource")
	if err == nil {
		t.Fatal("expected error for resourceID containing '.'")
	}
	want = "invalid resource id: resourceID must not contain '.'"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}

func TestAcquire_KeyValueFailure(t *testing.T) {
	defer setShortTimeouts(t)()

	js := &errJetStream{keyValueErr: errors.New("kv unavailable")}
	dl := &DistributedLock{js: js, bucketName: testBucketName}

	_, err := dl.Acquire(context.Background(), "test", "resource")
	if err == nil {
		t.Fatal("expected error when KeyValue fails")
	}
	want := "failed to get kv bucket: kv unavailable"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}

func TestAcquire_CreateOtherError(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	// Ensure the bucket exists so that Acquire only fails at kv.Create.
	if _, err := js.CreateKeyValue(&nats.KeyValueConfig{Bucket: testBucketName, TTL: lockTTL}); err != nil && !errors.Is(err, nats.ErrStreamNameAlreadyInUse) {
		t.Fatalf("failed to create test bucket: %v", err)
	}

	fkv := &failingKV{createErr: errors.New("create failed")}
	fjs := &fixedKVJetStream{JetStreamContext: js, kv: fkv}
	dl := &DistributedLock{js: fjs, bucketName: testBucketName}

	_, err := dl.Acquire(context.Background(), "test", "resource")
	if err == nil {
		t.Fatal("expected error when kv.Create fails")
	}
	want := "failed to create lock: create failed"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}

func TestRenew_ContextCancelledImmediately(t *testing.T) {
	defer setShortTimeouts(t)()

	lock := &Lock{
		kv:     &failingKV{},
		lostCh: make(chan struct{}),
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	lock.renewWg.Add(1)
	lock.renew(ctx, "key", "token")

	select {
	case <-lock.Lost():
		t.Fatal("Lost() should not be closed when context is already cancelled")
	default:
	}
}

func TestRenew_GetRepeatedError(t *testing.T) {
	defer setShortTimeouts(t)()

	kv := &countingFailingKV{}
	lock := &Lock{
		kv:     kv,
		lostCh: make(chan struct{}),
	}

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()

	lock.renewWg.Add(1)
	lock.renew(ctx, "key", "token")

	kv.mu.Lock()
	count := kv.getCount
	kv.mu.Unlock()
	if count == 0 {
		t.Fatal("expected renew to call Get at least once before context cancellation")
	}
}

func TestRenew_UpdateWrongLastSequence(t *testing.T) {
	defer setShortTimeouts(t)()

	lock := &Lock{
		kv:     &wrongSequenceKV{token: "token"},
		lostCh: make(chan struct{}),
	}

	lock.renewWg.Add(1)
	go lock.renew(context.Background(), "key", "token")

	select {
	case <-lock.Lost():
		// expected
	case <-time.After(2 * time.Second):
		t.Fatal("expected Lost() to be closed after wrong-last-sequence error")
	}
}

func TestIsHeld_GetError(t *testing.T) {
	lock := &Lock{
		kv:     &failingKV{getErr: errors.New("get failed")},
		lostCh: make(chan struct{}),
	}

	_, err := lock.IsHeld()
	if err == nil {
		t.Fatal("expected error when Get fails")
	}
	want := "failed to get lock entry: get failed"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}

func TestRelease_AlreadyReleased(t *testing.T) {
	defer setShortTimeouts(t)()

	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-release-twice")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	if err := lock.Release(); err != nil {
		t.Fatalf("first Release failed: %v", err)
	}
	if err := lock.Release(); err != nil {
		t.Fatalf("second Release should be idempotent, got: %v", err)
	}
}

func TestRelease_FirstGetTokenMismatch(t *testing.T) {
	lock := &Lock{
		lockType:     "test",
		resourceID:   "resource",
		fencingToken: "my-token",
		kv:           &tokenMismatchKV{actualToken: "other-token"},
		lostCh:       make(chan struct{}),
		cancel:       func() {},
	}

	err := lock.Release()
	if err == nil {
		t.Fatal("expected error when token mismatches on first Get")
	}
	if !errors.Is(err, ErrLockHeld) && err.Error() != `fencing token mismatch: cannot release lock held by another owner (expected="my-token", actual="other-token", revision=1)` {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestRelease_DeleteFailure(t *testing.T) {
	lock := &Lock{
		lockType:     "test",
		resourceID:   "resource",
		fencingToken: "my-token",
		kv:           &deleteFailureKV{token: "my-token", deleteErr: errors.New("delete failed")},
		lostCh:       make(chan struct{}),
		cancel:       func() {},
	}

	err := lock.Release()
	if err == nil {
		t.Fatal("expected error when Delete fails")
	}
	want := "failed to delete lock: delete failed"
	if err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}
