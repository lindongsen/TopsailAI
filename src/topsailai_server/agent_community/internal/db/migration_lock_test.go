package db

import (
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// newTestDB creates a fresh in-memory SQLite database migrated for use in tests.
func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	cfg := newTestConfig(sqliteInMemory(t))
	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })
	return db.Conn
}

// stubKVEntry implements nats.KeyValueEntry for testing.
type stubKVEntry struct {
	bucket   string
	key      string
	value    []byte
	revision uint64
	created  time.Time
}

func (e *stubKVEntry) Bucket() string                    { return e.bucket }
func (e *stubKVEntry) Key() string                       { return e.key }
func (e *stubKVEntry) Value() []byte                     { return e.value }
func (e *stubKVEntry) Revision() uint64                  { return e.revision }
func (e *stubKVEntry) Created() time.Time                { return e.created }
func (e *stubKVEntry) Delta() uint64                     { return 0 }
func (e *stubKVEntry) Operation() nats.KeyValueOp        { return nats.KeyValuePut }

// stubKeyValue is a minimal in-memory NATS KV implementation for testing the
// migration lock logic.
type stubKeyValue struct {
	mu      sync.RWMutex
	entries map[string]*stubKVEntry
}

func newStubKeyValue() *stubKeyValue {
	return &stubKeyValue{entries: make(map[string]*stubKVEntry)}
}

func (s *stubKeyValue) Get(key string) (nats.KeyValueEntry, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	entry, ok := s.entries[key]
	if !ok {
		return nil, nats.ErrKeyNotFound
	}
	return entry, nil
}

func (s *stubKeyValue) Create(key string, value []byte) (uint64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.entries[key]; exists {
		return 0, nats.ErrKeyExists
	}
	s.entries[key] = &stubKVEntry{
		bucket:   "test",
		key:      key,
		value:    value,
		revision: 1,
		created:  time.Now(),
	}
	return 1, nil
}

// Unimplemented methods below are not used by the migration lock logic.
func (s *stubKeyValue) GetRevision(key string, revision uint64) (nats.KeyValueEntry, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) Put(key string, value []byte) (uint64, error) {
	return 0, errors.New("unimplemented")
}
func (s *stubKeyValue) PutString(key string, value string) (uint64, error) {
	return 0, errors.New("unimplemented")
}
func (s *stubKeyValue) Update(key string, value []byte, last uint64) (uint64, error) {
	return 0, errors.New("unimplemented")
}
func (s *stubKeyValue) Delete(key string, opts ...nats.DeleteOpt) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.entries[key]; !ok {
		return nats.ErrKeyNotFound
	}
	delete(s.entries, key)
	return nil
}
func (s *stubKeyValue) Purge(key string, opts ...nats.DeleteOpt) error {
	return errors.New("unimplemented")
}
func (s *stubKeyValue) Watch(keys string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) WatchAll(opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) WatchFiltered(keys []string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) ListKeys(opts ...nats.WatchOpt) (nats.KeyLister, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) History(key string, opts ...nats.WatchOpt) ([]nats.KeyValueEntry, error) {
	return nil, errors.New("unimplemented")
}
func (s *stubKeyValue) Bucket() string { return "test" }
func (s *stubKeyValue) PurgeDeletes(opts ...nats.PurgeOpt) error {
	return errors.New("unimplemented")
}
func (s *stubKeyValue) Status() (nats.KeyValueStatus, error) {
	return nil, errors.New("unimplemented")
}

func TestMigrationLockKey_HasValidFormat(t *testing.T) {
	// The lock key must use dotted format and must not contain ':' which is
	// invalid in NATS KV key names.
	assert.Equal(t, "acs.lock.bootstrap.migration", migrationLockKey)
	assert.NotContains(t, migrationLockKey, ":")
}

func TestAutoMigrateWithLock_AcquiresAndReleasesLock(t *testing.T) {
	conn := newTestDB(t)
	kv := newStubKeyValue()

	err := autoMigrateWithLock(conn, kv)
	require.NoError(t, err)

	// Lock key should have been deleted after migration.
	_, err = kv.Get(migrationLockKey)
	assert.ErrorIs(t, err, nats.ErrKeyNotFound)
}

func TestAutoMigrateWithLock_WaitsForLockAndSkipsMigration(t *testing.T) {
	conn := newStubKeyValue()
	// Simulate another node holding the lock.
	_, err := conn.Create(migrationLockKey, []byte(uuid.New().String()))
	require.NoError(t, err)

	db := newTestDB(t)
	kv := conn

	// Release the lock after a short delay so the waiting node can proceed.
	go func() {
		time.Sleep(200 * time.Millisecond)
		_ = kv.Delete(migrationLockKey)
	}()

	start := time.Now()
	err = autoMigrateWithLock(db, kv)
	elapsed := time.Since(start)
	require.NoError(t, err)
	assert.True(t, elapsed >= 150*time.Millisecond, "should have waited for lock release")

	// Lock key should have been deleted after the waiting node finishes.
	_, err = kv.Get(migrationLockKey)
	assert.ErrorIs(t, err, nats.ErrKeyNotFound)
}
func TestAutoMigrateWithLock_NilKV_RunsWithoutLock(t *testing.T) {
	conn := newTestDB(t)

	err := autoMigrateWithLock(conn, nil)
	require.NoError(t, err)
}

func TestWaitForMigrationLockRelease_TimesOut(t *testing.T) {
	kv := newStubKeyValue()
	_, err := kv.Create(migrationLockKey, []byte("holder"))
	require.NoError(t, err)

	// Temporarily shorten the timeout to keep the test fast.
	origTimeout := migrationLockWaitTimeout
	migrationLockWaitTimeout = 100 * time.Millisecond
	defer func() { migrationLockWaitTimeout = origTimeout }()

	err = waitForMigrationLockRelease(kv)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "timed out")
}

func TestAutoMigrateWithLockFn_ReleasesLockOnPanic(t *testing.T) {
	conn := newTestDB(t)
	kv := newStubKeyValue()

	panickingMigrate := func(*gorm.DB) error {
		panic("intentional migration panic")
	}

	require.Panics(t, func() {
		_ = autoMigrateWithLockFn(conn, kv, panickingMigrate)
	})

	// Lock key should have been deleted despite the panic.
	_, err := kv.Get(migrationLockKey)
	assert.ErrorIs(t, err, nats.ErrKeyNotFound)
}
