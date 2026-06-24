// Package discovery provides NATS-based service discovery and leader election
// for the ACS (AI-Agent Community Server) cluster.
//
// Each service instance registers itself to a NATS KV bucket with a unique ID.
// Other instances can discover all registered services and determine whether
// the local instance is the Service-Leader (smallest ID wins).
//
// IMPORTANT: All ACS instances that should form a cluster MUST share the same
// NATS JetStream domain and the same ACS_DISCOVERY_BUCKET_NAME. A restarted
// node rejoins by writing to the same bucket with a deterministic service ID
// derived from its service name and listen address, which overwrites any stale
// registration left behind by the previous process.
package discovery

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"sync"
	"time"

	natsgo "github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/pkg/logger"
)

// ServiceInfo represents the registration information of a single ACS instance.
type ServiceInfo struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Address     string `json:"address"`
	Port        int    `json:"port"`
	Version     string `json:"version"`
	StartedAtMs int64  `json:"started_at_ms"`
}

// Config holds the configuration for service discovery.
type Config struct {
	ServiceName string
	Address     string
	Port        int
	Version     string
	BucketName  string
	Heartbeat   time.Duration
	TTL         time.Duration
}

// Discovery manages service registration, heartbeat, and leader election.
type Discovery struct {
	js     natsgo.JetStreamContext
	config Config
	self   ServiceInfo
	kv     natsgo.KeyValue

	mu      sync.RWMutex
	stopCh  chan struct{}
	wg      sync.WaitGroup
	started bool
}

// serviceID returns a deterministic identifier for a service instance.
// It is derived from the service name and listen address so that a restarted
// node on the same address reuses the same registration key, overwriting any
// stale entry left by the previous process.
func serviceID(serviceName, address string, port int) string {
	h := sha256.New()
	_, _ = h.Write([]byte(serviceName))
	_, _ = h.Write([]byte("|"))
	_, _ = h.Write([]byte(address))
	_, _ = h.Write([]byte(":"))
	_, _ = h.Write([]byte(strconv.Itoa(port)))
	return hex.EncodeToString(h.Sum(nil))[:32]
}

// New creates a new Discovery instance.
// It creates the NATS KV bucket if it does not already exist.
func New(js natsgo.JetStreamContext, config Config) (*Discovery, error) {
	if js == nil {
		return nil, fmt.Errorf("jetstream context is nil")
	}

	d := &Discovery{
		js:     js,
		config: config,
		self: ServiceInfo{
			ID:          serviceID(config.ServiceName, config.Address, config.Port),
			Name:        config.ServiceName,
			Address:     config.Address,
			Port:        config.Port,
			Version:     config.Version,
			StartedAtMs: time.Now().UnixMilli(),
		},
		stopCh: make(chan struct{}),
	}

	// Create or open the KV bucket.
	kv, err := js.CreateKeyValue(&natsgo.KeyValueConfig{
		Bucket:       config.BucketName,
		Description:  "ACS service discovery registry",
		TTL:          config.TTL,
		MaxValueSize: 8192,
		History:      1,
	})
	if err != nil {
		// Bucket may already exist.
		kv, err = js.KeyValue(config.BucketName)
		if err != nil {
			return nil, fmt.Errorf("failed to create or open KV bucket %s: %w", config.BucketName, err)
		}
	}
	d.kv = kv

	logger.InfoM("discovery", "", "discovery initialized",
		slog.String("bucket", config.BucketName),
		slog.String("service_id", d.self.ID),
		slog.String("address", fmt.Sprintf("%s:%d", config.Address, config.Port)),
	)

	return d, nil
}

// Register publishes the local service info to NATS KV and starts the heartbeat loop.
func (d *Discovery) Register() error {
	d.mu.Lock()
	defer d.mu.Unlock()

	if d.started {
		return fmt.Errorf("discovery already registered")
	}

	if err := d.upsertSelf(); err != nil {
		return fmt.Errorf("failed to register service: %w", err)
	}

	d.started = true
	d.wg.Add(1)
	go d.heartbeatLoop()

	logger.InfoM("discovery", "", "service registered",
		slog.String("bucket", d.config.BucketName),
		slog.String("service_id", d.self.ID),
		slog.String("address", fmt.Sprintf("%s:%d", d.config.Address, d.config.Port)),
	)

	return nil
}

// Deregister removes the local service info from NATS KV and stops the heartbeat loop.
func (d *Discovery) Deregister() error {
	d.mu.Lock()
	if !d.started {
		d.mu.Unlock()
		return nil
	}
	d.started = false
	close(d.stopCh)
	d.mu.Unlock()

	d.wg.Wait()

	if d.kv != nil {
		if err := d.kv.Delete(d.self.ID); err != nil {
			return fmt.Errorf("failed to delete service registration: %w", err)
		}
	}

	logger.InfoM("discovery", "", "service deregistered",
		slog.String("bucket", d.config.BucketName),
		slog.String("service_id", d.self.ID),
	)

	return nil
}

// SelfInfo returns the local service's registration info.
func (d *Discovery) SelfInfo() ServiceInfo {
	if d == nil {
		return ServiceInfo{}
	}
	d.mu.RLock()
	defer d.mu.RUnlock()
	return d.self
}

// Enabled reports whether service discovery is active.
func (d *Discovery) Enabled() bool {
	return d != nil
}

// Discover fetches all currently registered services from NATS KV.
func (d *Discovery) Discover() ([]ServiceInfo, error) {
	if d == nil {
		return nil, fmt.Errorf("discovery not initialized")
	}
	if d.kv == nil {
		return nil, fmt.Errorf("kv store not initialized")
	}

	keys, err := d.kv.Keys()
	if err != nil {
		// NATS returns ErrNoKeysFound when the bucket is empty.
		if err == natsgo.ErrNoKeysFound {
			return []ServiceInfo{}, nil
		}
		return nil, fmt.Errorf("failed to list keys: %w", err)
	}

	services := make([]ServiceInfo, 0, len(keys))
	for _, key := range keys {
		entry, err := d.kv.Get(key)
		if err != nil {
			// Entry may have expired between Keys() and Get().
			continue
		}

		var info ServiceInfo
		if err := json.Unmarshal(entry.Value(), &info); err != nil {
			continue
		}
		services = append(services, info)
	}

	return services, nil
}

// IsLeader returns true if the local service has the smallest ID among all registered services.
func (d *Discovery) IsLeader() (bool, error) {
	if d == nil {
		return false, fmt.Errorf("discovery not initialized")
	}
	services, err := d.Discover()
	if err != nil {
		return false, err
	}

	if len(services) == 0 {
		// No other services; this instance is the leader by default.
		return true, nil
	}

	// Find the smallest ID.
	leaderID := services[0].ID
	for _, svc := range services {
		if svc.ID < leaderID {
			leaderID = svc.ID
		}
	}

	return d.self.ID == leaderID, nil
}

// LeaderInfo returns the ServiceInfo of the current leader, or nil if no services are registered.
func (d *Discovery) LeaderInfo() (*ServiceInfo, error) {
	if d == nil {
		return nil, fmt.Errorf("discovery not initialized")
	}
	services, err := d.Discover()
	if err != nil {
		return nil, err
	}

	if len(services) == 0 {
		return nil, nil
	}

	// Sort by ID ascending to find the leader.
	sort.Slice(services, func(i, j int) bool {
		return services[i].ID < services[j].ID
	})

	return &services[0], nil
}

// upsertSelf writes the local service info to NATS KV.
func (d *Discovery) upsertSelf() error {
	data, err := json.Marshal(d.self)
	if err != nil {
		return fmt.Errorf("failed to marshal service info: %w", err)
	}

	_, err = d.kv.Put(d.self.ID, data)
	if err != nil {
		return fmt.Errorf("failed to put service info: %w", err)
	}

	return nil
}

// heartbeatLoop periodically updates the service registration in NATS KV.
func (d *Discovery) heartbeatLoop() {
	defer d.wg.Done()

	ticker := time.NewTicker(d.config.Heartbeat)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if err := d.upsertSelf(); err != nil {
				// Log error but keep trying; NATS may be temporarily unavailable.
				logger.WarnM("discovery", "", "heartbeat upsert failed",
					slog.String("service_id", d.self.ID),
					slog.String("error", err.Error()),
				)
				continue
			}
			logger.DebugM("discovery", "", "heartbeat upsert succeeded",
				slog.String("service_id", d.self.ID),
			)
		case <-d.stopCh:
			return
		}
	}
}
