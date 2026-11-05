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

// Registry contains explicitly registered adapter factories.
type Registry struct {
	mu        sync.RWMutex
	factories map[string]Factory
	instances map[string]Adapter
}

// NewRegistry returns an empty explicit adapter registry.
func NewRegistry() *Registry {
	return &Registry{factories: make(map[string]Factory), instances: make(map[string]Adapter)}
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
	instance, err := factory(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("configure adapter %q: %w", config.AdapterID, err)
	}
	r.instances[config.AdapterID] = instance
	return instance, nil
}

// Get returns a configured instance by its stable local adapter ID.
func (r *Registry) Get(adapterID string) (Adapter, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	instance, ok := r.instances[adapterID]
	return instance, ok
}

// All returns a detached snapshot of configured instances for read-only discovery.
func (r *Registry) All() []Adapter {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]Adapter, 0, len(r.instances))
	for _, instance := range r.instances {
		result = append(result, instance)
	}
	return result
}
