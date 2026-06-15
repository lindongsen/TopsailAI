package discovery

import (
	"encoding/json"
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

	// Allow heartbeat to run
	time.Sleep(200 * time.Millisecond)

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

	// Allow heartbeat to run
	time.Sleep(200 * time.Millisecond)

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
