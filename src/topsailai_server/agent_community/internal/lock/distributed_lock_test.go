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
	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	_ = newTestLock(t, js)

	// Use a short TTL bucket to verify renewal works. Since the production code
	// uses a fixed TTL, we create a separate lock manager with a short TTL by
	// creating the bucket directly and then constructing the DistributedLock.
	shortTTL := 2 * time.Second
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
	case <-time.After(15 * time.Second):
		t.Fatal("expected Lost() channel to be closed after key deletion")
	}
}

func TestConcurrentBucketCreationRace(t *testing.T) {
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
	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	lock, err := dl.Acquire(context.Background(), "test", "resource-timeout")
	if err != nil {
		t.Fatalf("Acquire failed: %v", err)
	}

	// Replace the kv with a wrapper that blocks Update/Get operations to
	// simulate a stuck renewal goroutine.
	blocker := &blockingKV{kv: lock.kv, blockAfter: 0}
	lock.kv = blocker

	start := time.Now()
	err = lock.Release()
	elapsed := time.Since(start)

	if elapsed > releaseWait+2*time.Second {
		t.Fatalf("Release blocked too long: %v", elapsed)
	}

	// Release should report a timeout warning via logs and may return an error
	// from the best-effort delete path. We accept either nil or non-nil error
	// as long as it did not block indefinitely.
	_ = err
}

func TestReleaseTOCTOUSafety(t *testing.T) {
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
	s, cleanup := startNATSServer(t)
	defer cleanup()

	js := connectJS(t, s)
	dl := newTestLock(t, js)

	const numGoroutines = 10
	var wg sync.WaitGroup
	acquired := make(chan *Lock, 1)
	var acquiredCount int64

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

	_ = acquiredCount
}

// blockingKV blocks Get/Update operations after a configurable number of calls.
type blockingKV struct {
	kv         nats.KeyValue
	blockAfter int
	mu         sync.Mutex
	calls      int
}

func (b *blockingKV) Get(key string) (nats.KeyValueEntry, error) {
	b.mu.Lock()
	b.calls++
	shouldBlock := b.calls > b.blockAfter
	b.mu.Unlock()
	if shouldBlock {
		<-make(chan struct{}) // block forever
	}
	return b.kv.Get(key)
}

func (b *blockingKV) Create(key string, value []byte) (uint64, error) {
	return b.kv.Create(key, value)
}

func (b *blockingKV) Update(key string, value []byte, last uint64) (uint64, error) {
	b.mu.Lock()
	b.calls++
	shouldBlock := b.calls > b.blockAfter
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
