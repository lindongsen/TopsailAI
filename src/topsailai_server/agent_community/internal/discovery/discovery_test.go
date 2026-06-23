package discovery

import (
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// startEmbeddedNATSServer starts an in-memory NATS server with JetStream enabled.
func startEmbeddedNATSServer(t *testing.T) (*server.Server, nats.JetStreamContext) {
	t.Helper()

	opts := &server.Options{
		Port:      -1,
		JetStream: true,
		StoreDir:  t.TempDir(),
	}

	ns, err := server.NewServer(opts)
	require.NoError(t, err)
	go ns.Start()
	ns.ReadyForConnections(5 * time.Second)
	t.Cleanup(ns.Shutdown)

	nc, err := nats.Connect(ns.ClientURL())
	require.NoError(t, err)
	t.Cleanup(nc.Close)

	js, err := nc.JetStream()
	require.NoError(t, err)

	return ns, js
}

func TestNewDiscovery(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	cfg := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  "test_discovery_bucket",
		Heartbeat:   5 * time.Second,
		TTL:         30 * time.Second,
	}

	d, err := New(js, cfg)
	require.NoError(t, err)
	assert.NotNil(t, d)
	assert.NotEmpty(t, d.self.ID)
	assert.Equal(t, "acs", d.self.Name)
	assert.Equal(t, "127.0.0.1", d.self.Address)
	assert.Equal(t, 7370, d.self.Port)
	assert.Equal(t, "1.0.0", d.self.Version)
	assert.NotZero(t, d.self.StartedAtMs)
}

func TestDiscovery_RegisterAndDeregister(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	cfg := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  "test_reg_bucket",
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}

	d, err := New(js, cfg)
	require.NoError(t, err)

	// Register
	err = d.Register()
	require.NoError(t, err)
	assert.True(t, d.started)

	// Verify registration exists in KV
	entry, err := d.kv.Get(d.self.ID)
	require.NoError(t, err)

	var info ServiceInfo
	err = json.Unmarshal(entry.Value(), &info)
	require.NoError(t, err)
	assert.Equal(t, d.self.ID, info.ID)
	assert.Equal(t, "acs", info.Name)

	// Deregister
	err = d.Deregister()
	require.NoError(t, err)
	assert.False(t, d.started)

	// Verify registration removed
	_, err = d.kv.Get(d.self.ID)
	assert.Error(t, err) // should be not found
}

func TestDiscovery_Discover(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	bucketName := "test_discover_bucket"

	// Create first instance
	cfg1 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d1, err := New(js, cfg1)
	require.NoError(t, err)
	err = d1.Register()
	require.NoError(t, err)
	defer d1.Deregister()

	// Create second instance
	cfg2 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7371,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d2, err := New(js, cfg2)
	require.NoError(t, err)
	err = d2.Register()
	require.NoError(t, err)
	defer d2.Deregister()

	// Wait until both registrations are visible.
	require.Eventually(t, func() bool {
		services, err := d1.Discover()
		if err != nil {
			return false
		}
		return len(services) == 2
	}, 2*time.Second, 50*time.Millisecond)

	// Discover from d1
	services, err := d1.Discover()
	require.NoError(t, err)
	assert.Len(t, services, 2)

	ids := make(map[string]bool)
	for _, s := range services {
		ids[s.ID] = true
	}
	assert.True(t, ids[d1.self.ID])
	assert.True(t, ids[d2.self.ID])
}

func TestDiscovery_IsLeader(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	bucketName := "test_leader_bucket"

	// Create first instance
	cfg1 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d1, err := New(js, cfg1)
	require.NoError(t, err)
	err = d1.Register()
	require.NoError(t, err)
	defer d1.Deregister()

	// Single instance should be leader
	isLeader, err := d1.IsLeader()
	require.NoError(t, err)
	assert.True(t, isLeader)

	// Create second instance
	cfg2 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7371,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d2, err := New(js, cfg2)
	require.NoError(t, err)
	err = d2.Register()
	require.NoError(t, err)
	defer d2.Deregister()

	// Allow heartbeat to run
	time.Sleep(200 * time.Millisecond)

	// Determine which ID is smaller
	if d1.self.ID < d2.self.ID {
		isLeader1, _ := d1.IsLeader()
		isLeader2, _ := d2.IsLeader()
		assert.True(t, isLeader1)
		assert.False(t, isLeader2)
	} else {
		isLeader1, _ := d1.IsLeader()
		isLeader2, _ := d2.IsLeader()
		assert.False(t, isLeader1)
		assert.True(t, isLeader2)
	}
}

func TestDiscovery_LeaderInfo(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	bucketName := "test_leader_info_bucket"

	// Create first instance
	cfg1 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d1, err := New(js, cfg1)
	require.NoError(t, err)
	err = d1.Register()
	require.NoError(t, err)
	defer d1.Deregister()

	// Single instance: leader info should be self
	leader, err := d1.LeaderInfo()
	require.NoError(t, err)
	require.NotNil(t, leader)
	assert.Equal(t, d1.self.ID, leader.ID)

	// Create second instance
	cfg2 := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7371,
		Version:     "1.0.0",
		BucketName:  bucketName,
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}
	d2, err := New(js, cfg2)
	require.NoError(t, err)
	err = d2.Register()
	require.NoError(t, err)
	defer d2.Deregister()

	// Wait until both registrations are visible.
	require.Eventually(t, func() bool {
		services, err := d1.Discover()
		if err != nil {
			return false
		}
		return len(services) == 2
	}, 2*time.Second, 50*time.Millisecond)

	// LeaderInfo should return the instance with smallest ID
	leader, err = d1.LeaderInfo()
	require.NoError(t, err)
	require.NotNil(t, leader)

	if d1.self.ID < d2.self.ID {
		assert.Equal(t, d1.self.ID, leader.ID)
	} else {
		assert.Equal(t, d2.self.ID, leader.ID)
	}
}

func TestDiscovery_DiscoverEmptyBucket(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	cfg := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  "test_empty_bucket",
		Heartbeat:   5 * time.Second,
		TTL:         30 * time.Second,
	}

	d, err := New(js, cfg)
	require.NoError(t, err)

	// Do not register; bucket is empty
	services, err := d.Discover()
	require.NoError(t, err)
	assert.Empty(t, services)
}

func TestDiscovery_DoubleRegister(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	cfg := Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		Version:     "1.0.0",
		BucketName:  "test_double_reg",
		Heartbeat:   100 * time.Millisecond,
		TTL:         30 * time.Second,
	}

	d, err := New(js, cfg)
	require.NoError(t, err)

	err = d.Register()
	require.NoError(t, err)
	defer d.Deregister()

	// Second register should fail
	err = d.Register()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "already registered")
}

func TestDiscovery_SelfInfo(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	cfg := Config{
		ServiceName: "acs",
		Address:     "192.168.1.1",
		Port:        8080,
		Version:     "2.0.0",
		BucketName:  "test_self_info",
		Heartbeat:   5 * time.Second,
		TTL:         30 * time.Second,
	}

	d, err := New(js, cfg)
	require.NoError(t, err)

	info := d.SelfInfo()
	assert.Equal(t, "acs", info.Name)
	assert.Equal(t, "192.168.1.1", info.Address)
	assert.Equal(t, 8080, info.Port)
	assert.Equal(t, "2.0.0", info.Version)
	assert.NotEmpty(t, info.ID)
	assert.NotZero(t, info.StartedAtMs)
}

// errJetStream is a JetStream stub that returns configurable errors for
// KeyValue and CreateKeyValue. It is used to exercise New error paths
// without a real NATS server.
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

// fakeEntry is a minimal KeyValueEntry implementation for stubs.
type fakeEntry struct {
	bucket   string
	key      string
	value    []byte
	revision uint64
}

func (f *fakeEntry) Bucket() string             { return f.bucket }
func (f *fakeEntry) Key() string                { return f.key }
func (f *fakeEntry) Value() []byte              { return f.value }
func (f *fakeEntry) Revision() uint64           { return f.revision }
func (f *fakeEntry) Created() time.Time         { return time.Now() }
func (f *fakeEntry) Delta() uint64              { return 0 }
func (f *fakeEntry) Operation() nats.KeyValueOp { return nats.KeyValuePut }

// failingKV is a KeyValue stub that returns configured errors for Get, Keys,
// Put and Delete. All other methods are not expected to be called.
type failingKV struct {
	nats.KeyValue
	keysErr   error
	putErr    error
	deleteErr error
}

func (f *failingKV) Get(key string) (nats.KeyValueEntry, error) {
	return nil, f.keysErr
}

func (f *failingKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return nil, f.keysErr
}

func (f *failingKV) Put(key string, value []byte) (uint64, error) {
	return 0, f.putErr
}

func (f *failingKV) Delete(key string, opts ...nats.DeleteOpt) error {
	return f.deleteErr
}

// invalidJSONKV returns an entry whose value is not valid JSON.
type invalidJSONKV struct {
	nats.KeyValue
}

func (i *invalidJSONKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return []string{"bad-key"}, nil
}

func (i *invalidJSONKV) Get(key string) (nats.KeyValueEntry, error) {
	return &fakeEntry{bucket: "test", key: key, value: []byte("not-json")}, nil
}

// mixedKV returns one valid and one invalid entry.
type mixedKV struct {
	nats.KeyValue
}

func (m *mixedKV) Keys(opts ...nats.WatchOpt) ([]string, error) {
	return []string{"valid", "invalid"}, nil
}

func (m *mixedKV) Get(key string) (nats.KeyValueEntry, error) {
	if key == "valid" {
		data, _ := json.Marshal(ServiceInfo{ID: "valid-id", Name: "acs"})
		return &fakeEntry{bucket: "test", key: key, value: data}, nil
	}
	return &fakeEntry{bucket: "test", key: key, value: []byte("not-json")}, nil
}

func TestNewDiscovery_NilJetStream(t *testing.T) {
	_, err := New(nil, Config{BucketName: "test"})
	require.Error(t, err)
	assert.Equal(t, "jetstream context is nil", err.Error())
}

func TestNewDiscovery_CreateKeyValueOtherError(t *testing.T) {
	// New first calls KeyValue (which fails with "bucket not found"), then
	// falls back to CreateKeyValue (which also fails with "create failed").
	// The returned error combines both failures.
	js := &errJetStream{
		keyValueErr: errors.New("bucket not found"),
		createErr:   errors.New("create failed"),
	}
	_, err := New(js, Config{BucketName: "test"})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "bucket not found")
}

func TestNewDiscovery_BucketAlreadyExists(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	bucketName := "test_bucket_already_exists"
	_, err := js.CreateKeyValue(&nats.KeyValueConfig{
		Bucket: bucketName,
		TTL:    30 * time.Second,
	})
	require.NoError(t, err)

	d, err := New(js, Config{BucketName: bucketName})
	require.NoError(t, err)
	assert.NotNil(t, d)
	assert.NotNil(t, d.kv)
}

func TestRegister_AlreadyRegistered(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	d, err := New(js, Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		BucketName:  "test_already_registered",
		Heartbeat:   5 * time.Second,
		TTL:         30 * time.Second,
	})
	require.NoError(t, err)

	err = d.Register()
	require.NoError(t, err)
	defer d.Deregister()

	err = d.Register()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "already registered")
}

func TestRegister_UpsertSelfFailure(t *testing.T) {
	fkv := &failingKV{putErr: errors.New("put failed")}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js:     fjs,
		config: Config{BucketName: "test_upsert_failure"},
		self:   ServiceInfo{ID: "self-id"},
		kv:     fkv,
		stopCh: make(chan struct{}),
	}

	err := d.Register()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "put failed")
	assert.False(t, d.started)
}

func TestDeregister_NotRegistered(t *testing.T) {
	_, js := startEmbeddedNATSServer(t)

	d, err := New(js, Config{
		ServiceName: "acs",
		Address:     "127.0.0.1",
		Port:        7370,
		BucketName:  "test_deregister_not_registered",
		Heartbeat:   5 * time.Second,
		TTL:         30 * time.Second,
	})
	require.NoError(t, err)

	err = d.Deregister()
	require.NoError(t, err)
}

func TestDeregister_DeleteFailure(t *testing.T) {
	fkv := &failingKV{deleteErr: errors.New("delete failed")}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js:      fjs,
		config:  Config{BucketName: "test_delete_failure"},
		self:    ServiceInfo{ID: "self-id"},
		kv:      fkv,
		stopCh:  make(chan struct{}),
		started: true,
	}

	err := d.Deregister()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "delete failed")
}

func TestDiscover_KVNil(t *testing.T) {
	d := &Discovery{kv: nil}
	_, err := d.Discover()
	require.Error(t, err)
	assert.Equal(t, "kv store not initialized", err.Error())
}

func TestDiscover_KeysError(t *testing.T) {
	fkv := &failingKV{keysErr: errors.New("keys failed")}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js: fjs,
		kv: fkv,
	}

	_, err := d.Discover()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "keys failed")
}

func TestDiscover_InvalidJSONEntry(t *testing.T) {
	fkv := &invalidJSONKV{}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js: fjs,
		kv: fkv,
	}

	services, err := d.Discover()
	require.NoError(t, err)
	assert.Empty(t, services)
}

func TestDiscover_MixedValidInvalidEntries(t *testing.T) {
	fkv := &mixedKV{}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js: fjs,
		kv: fkv,
	}

	services, err := d.Discover()
	require.NoError(t, err)
	require.Len(t, services, 1)
	assert.Equal(t, "valid-id", services[0].ID)
}

func TestIsLeader_EmptyServices(t *testing.T) {
	fkv := &failingKV{keysErr: nats.ErrNoKeysFound}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js:   fjs,
		kv:   fkv,
		self: ServiceInfo{ID: "self-id"},
	}

	isLeader, err := d.IsLeader()
	require.NoError(t, err)
	assert.True(t, isLeader)
}

func TestLeaderInfo_EmptyServices(t *testing.T) {
	fkv := &failingKV{keysErr: nats.ErrNoKeysFound}
	fjs := &fixedKVJetStream{kv: fkv}

	d := &Discovery{
		js:   fjs,
		kv:   fkv,
		self: ServiceInfo{ID: "self-id"},
	}

	leader, err := d.LeaderInfo()
	require.NoError(t, err)
	assert.Nil(t, leader)
}

func TestUpsertSelf_PutFailure(t *testing.T) {
	fkv := &failingKV{putErr: errors.New("put failed")}

	d := &Discovery{
		kv:   fkv,
		self: ServiceInfo{ID: "self-id"},
	}

	err := d.upsertSelf()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "put failed")
}

func TestHeartbeatLoop_StopWhileWaiting(t *testing.T) {
	fkv := &failingKV{}

	d := &Discovery{
		config: Config{Heartbeat: 10 * time.Second},
		kv:     fkv,
		stopCh: make(chan struct{}),
	}

	d.wg.Add(1)
	go d.heartbeatLoop()

	// Stop immediately while the goroutine is waiting on the ticker.
	close(d.stopCh)

	done := make(chan struct{})
	go func() {
		d.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		// expected
	case <-time.After(2 * time.Second):
		t.Fatal("heartbeatLoop did not stop in time")
	}
}
