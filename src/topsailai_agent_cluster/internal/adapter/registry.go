package adapter

import (
	"context"
	"fmt"
	"sync"

	"topsailai_agent_cluster/internal/protocol"
)

// Factory constructs one configured adapter instance.
type Factory func(context.Context, Config) (Adapter, error)

// Config is local Endpoint configuration and is never supplied by Server payloads.
type Config struct {
	AdapterID    string
	ProviderType string
	DisplayName  string
	Command      string
	Args         []string
	TimeoutMS    int64
	Settings     map[string]string
	Capabilities *protocol.CapabilityDescriptor
}

// instance holds one configured adapter together with the number of callers that
// are still using it.
//
// The reference count exists so a Provider CLI version can be replaced while work
// is in flight. A caller that acquired the instance keeps using it until it
// releases, which is what makes an in-flight command or a long output stream
// finish on the version it started on instead of being silently redirected to a
// version it never validated against. A retired instance is closed only after its
// last caller releases, so replacing a version never closes a process that is
// still serving a request.
//
// The configuration is retained because a replacement has to reuse everything the
// operator did not change. Only the executable path names the version, so a
// candidate is built from the previous configuration with one field overridden;
// rebuilding from scratch would silently drop the timeout, the arguments and the
// declared capabilities.
type instance struct {
	adapterID string
	adapter   Adapter
	config    Config
	refs      int
	retired   bool
}

// Registry contains explicitly registered adapter factories.
type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
	instances map[string]*instance
	// draining holds retired instances that still have callers. They are kept so
	// activation can report how much work is still finishing on the previous
	// version instead of claiming an immediate clean handover.
	draining map[string][]*instance
}

// NewRegistry returns an empty explicit adapter registry.
func NewRegistry() *Registry {
	return &Registry{
		factories: make(map[string]Factory),
		instances: make(map[string]*instance),
		draining:  make(map[string][]*instance),
	}
}

// RegisterType registers one provider type without plugin loading or hot reload.
func (r *Registry) RegisterType(providerType string, factory Factory) error {
	if providerType == "" || factory == nil {
		return fmt.Errorf("provider type and factory are required")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.factories[providerType]; exists {
		return fmt.Errorf("provider type %q already registered", providerType)
	}
	r.factories[providerType] = factory
	return nil
}

// Configure creates and stores one stable adapter instance.
func (r *Registry) Configure(ctx context.Context, config Config) (Adapter, error) {
	if config.AdapterID == "" || config.ProviderType == "" {
		return nil, fmt.Errorf("adapter ID and provider type are required")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.instances[config.AdapterID]; exists {
		return nil, fmt.Errorf("adapter ID %q already configured", config.AdapterID)
	}
	factory, exists := r.factories[config.ProviderType]
	if !exists {
		return nil, fmt.Errorf("provider type %q is not registered", config.ProviderType)
	}
	configured, err := factory(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("configure adapter %q: %w", config.AdapterID, err)
	}
	r.instances[config.AdapterID] = &instance{adapterID: config.AdapterID, adapter: configured, config: config}
	return configured, nil
}

// Prepare builds one candidate instance without registering it.
//
// It exists for activation: a candidate Provider CLI version must be constructed
// and validated before it can replace anything, and a candidate that fails
// validation must leave the registry untouched. Configure cannot serve that
// purpose because it rejects an adapter ID that is already configured, which is
// exactly the ID a replacement targets.
//
// The factory runs outside the registry lock, so a slow candidate bootstrap never
// blocks command dispatch on the versions that are already serving.
func (r *Registry) Prepare(ctx context.Context, config Config) (Adapter, error) {
	if config.AdapterID == "" || config.ProviderType == "" {
		return nil, fmt.Errorf("adapter ID and provider type are required")
	}
	r.mu.RLock()
	factory, exists := r.factories[config.ProviderType]
	r.mu.RUnlock()
	if !exists {
		return nil, fmt.Errorf("provider type %q is not registered", config.ProviderType)
	}
	configured, err := factory(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("configure adapter %q: %w", config.AdapterID, err)
	}
	return configured, nil
}

// Config returns the configuration one adapter was built from.
//
// Activation reads it to reuse the timeout, arguments and declared capabilities
// the operator configured, so a replacement changes only the executable path.
func (r *Registry) Config(adapterID string) (Config, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	entry, ok := r.instances[adapterID]
	if !ok {
		return Config{}, false
	}
	return entry.config, true
}

// Get returns a configured instance by its stable local adapter ID.
//
// It is the read-only accessor used by bounded listing paths, which only read a
// descriptor and never run provider work. A caller that runs provider work must
// use Acquire instead, because only Acquire keeps the instance alive across a
// replacement.
func (r *Registry) Get(adapterID string) (Adapter, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	entry, ok := r.instances[adapterID]
	if !ok {
		return nil, false
	}
	return entry.adapter, true
}

// All returns a detached snapshot of configured instances for read-only discovery.
func (r *Registry) All() []Adapter {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]Adapter, 0, len(r.instances))
	for _, entry := range r.instances {
		result = append(result, entry.adapter)
	}
	return result
}

// Acquire returns the current instance for one adapter and a release function.
//
// The returned instance stays usable until release is called, even if the adapter
// is replaced in the meantime. Release is idempotent so a caller can defer it
// without tracking whether it already ran.
func (r *Registry) Acquire(adapterID string) (Adapter, func(), bool) {
	r.mu.Lock()
	entry, ok := r.instances[adapterID]
	if !ok {
		r.mu.Unlock()
		return nil, nil, false
	}
	entry.refs++
	configured := entry.adapter
	r.mu.Unlock()
	var once sync.Once
	release := func() {
		once.Do(func() { r.release(entry) })
	}
	return configured, release, true
}

// AcquireAll returns every configured instance together with one release function.
//
// It exists for the bounded read paths that must consult every adapter, such as a
// launch catalog or a conversation read. Holding a reference for the whole scan
// means a replacement that lands mid-scan cannot close an instance the scan is
// still calling, and the scan finishes on the versions it started with.
func (r *Registry) AcquireAll() ([]Adapter, func()) {
	r.mu.Lock()
	entries := make([]*instance, 0, len(r.instances))
	result := make([]Adapter, 0, len(r.instances))
	for _, entry := range r.instances {
		entry.refs++
		entries = append(entries, entry)
		result = append(result, entry.adapter)
	}
	r.mu.Unlock()
	var once sync.Once
	release := func() {
		once.Do(func() {
			for _, entry := range entries {
				r.release(entry)
			}
		})
	}
	return result, release
}

// release decrements one reference and closes a retired instance when it becomes
// unreachable. Closing happens outside the registry lock so a slow Close cannot
// block every other adapter lookup.
func (r *Registry) release(entry *instance) {
	r.mu.Lock()
	if entry.refs > 0 {
		entry.refs--
	}
	closeNow := entry.retired && entry.refs == 0
	if closeNow {
		r.forgetDraining(entry)
	}
	r.mu.Unlock()
	if closeNow {
		_ = entry.adapter.Close()
	}
}

// forgetDraining removes one retired instance from the draining list. The caller
// must hold the write lock.
func (r *Registry) forgetDraining(entry *instance) {
	entries := r.draining[entry.adapterID]
	for index, candidate := range entries {
		if candidate != entry {
			continue
		}
		entries = append(entries[:index], entries[index+1:]...)
		break
	}
	if len(entries) == 0 {
		delete(r.draining, entry.adapterID)
		return
	}
	r.draining[entry.adapterID] = entries
}

// Replace atomically swaps the instance registered for one adapter ID and returns
// the instance that was replaced.
//
// The swap is a single map assignment under the write lock, so a concurrent
// Acquire observes either the previous instance or the next one and never a
// partially configured adapter. The previous instance is retired rather than
// closed: callers that already acquired it keep working, and it is closed when
// the last of them releases. A failed replacement therefore leaves the previous
// version serving traffic, which is the property that makes activation safe.
func (r *Registry) Replace(adapterID string, next Adapter) (Adapter, error) {
	return r.ReplaceWithConfig(adapterID, next, Config{})
}

// ReplaceWithConfig swaps the instance and records the configuration the new
// instance was built from, so a later replacement or rollback reuses it.
//
// An empty configuration keeps the previous one, which is what a caller that only
// has a new instance can supply.
func (r *Registry) ReplaceWithConfig(adapterID string, next Adapter, config Config) (Adapter, error) {
	if adapterID == "" {
		return nil, fmt.Errorf("adapter ID is required")
	}
	if next == nil {
		return nil, fmt.Errorf("replacement adapter is required")
	}
	r.mu.Lock()
	previous, exists := r.instances[adapterID]
	if !exists {
		r.mu.Unlock()
		return nil, fmt.Errorf("adapter ID %q is not configured", adapterID)
	}
	if previous.adapter == next {
		r.mu.Unlock()
		return nil, fmt.Errorf("adapter ID %q already uses the requested instance", adapterID)
	}
	effective := config
	if effective.AdapterID == "" {
		effective = previous.config
	}
	previous.retired = true
	r.instances[adapterID] = &instance{adapterID: adapterID, adapter: next, config: effective}
	closeNow := previous.refs == 0
	if !closeNow {
		r.draining[adapterID] = append(r.draining[adapterID], previous)
	}
	r.mu.Unlock()
	if closeNow {
		_ = previous.adapter.Close()
	}
	return previous.adapter, nil
}

// RestoreWithConfig reinstates an instance that a previous replacement retired.
//
// It exists for rollback. ReplaceWithConfig cannot serve that purpose because it
// installs the supplied adapter in a fresh instance record, which would leave the
// retired record still holding a reference count: when its last caller released,
// it would close the very adapter that had just been restored. Restoring the
// original record instead keeps the reference count attached to the instance that
// is serving again, so a caller that was mid-request when the replacement happened
// still finishes on the version it started on and nothing closes it underneath.
//
// It fails when the previous instance is no longer available, which happens when
// nothing held it at replacement time and it was therefore closed immediately. A
// caller that needs rollback in that case must rebuild the previous version from
// its configuration instead of restoring the closed instance.
func (r *Registry) RestoreWithConfig(adapterID string, previous Adapter, config Config) error {
	if adapterID == "" {
		return fmt.Errorf("adapter ID is required")
	}
	if previous == nil {
		return fmt.Errorf("previous adapter is required")
	}
	r.mu.Lock()
	current, exists := r.instances[adapterID]
	if !exists {
		r.mu.Unlock()
		return fmt.Errorf("adapter ID %q is not configured", adapterID)
	}
	var restored *instance
	for _, candidate := range r.draining[adapterID] {
		if candidate.adapter == previous {
			restored = candidate
			break
		}
	}
	if restored == nil {
		r.mu.Unlock()
		return fmt.Errorf("previous instance for adapter %q is no longer available", adapterID)
	}
	r.forgetDraining(restored)
	restored.retired = false
	if config.AdapterID != "" {
		restored.config = config
	}
	current.retired = true
	closeNow := current.refs == 0
	if !closeNow {
		r.draining[adapterID] = append(r.draining[adapterID], current)
	}
	r.instances[adapterID] = restored
	r.mu.Unlock()
	if closeNow {
		_ = current.adapter.Close()
	}
	return nil
}

// InFlight reports how many callers still hold an instance for one adapter,
// including callers finishing on a retired version. It exists so activation can
// report whether a replacement is still draining instead of claiming an immediate
// clean handover.
func (r *Registry) InFlight(adapterID string) int {
	r.mu.RLock()
	defer r.mu.RUnlock()
	total := 0
	if entry, ok := r.instances[adapterID]; ok {
		total += entry.refs
	}
	for _, entry := range r.draining[adapterID] {
		total += entry.refs
	}
	return total
}
