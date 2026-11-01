package main

import (
	"context"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	topsailaiadapter "topsailai_agent_cluster/internal/adapter/topsailai"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

func registerAdapterType(registry *adapter.Registry, providerType string, store *endpointstorage.Store) error {
	if registry == nil || store == nil {
		return fmt.Errorf("registry and store are required")
	}
	var factory adapter.Factory
	switch providerType {
	case "topsailai":
		factory = func(_ context.Context, local adapter.Config) (adapter.Adapter, error) {
			return topsailaiadapter.New(topsailaiadapter.Config{
				AdapterID: local.AdapterID, Executable: local.Command,
				Timeout:        time.Duration(local.TimeoutMS) * time.Millisecond,
				ResourceMapper: store,
			})
		}
	case "fixture", "command":
		factory = func(_ context.Context, local adapter.Config) (adapter.Adapter, error) {
			return adapter.NewCommandAdapter(adapter.CommandConfig{
				AdapterID: local.AdapterID, ProviderType: local.ProviderType,
				Command: local.Command, Args: local.Args,
				Timeout:        time.Duration(local.TimeoutMS) * time.Millisecond,
				ResourceMapper: store, Capabilities: local.Capabilities,
			})
		}
	default:
		return fmt.Errorf("unknown adapter provider type %q", providerType)
	}
	return registry.RegisterType(providerType, factory)
}
