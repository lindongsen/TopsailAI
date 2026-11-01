// Package endpoint provides Endpoint-side collection and inventory composition.
package endpoint

import (
	"context"
	"fmt"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// Binding associates one configured adapter instance with its descriptive metadata.
type Binding struct {
	AdapterID    string
	ProviderType string
	DisplayName  string
	Version      string
	Capabilities protocol.CapabilityDescriptor
	Adapter      adapter.Adapter
}

// Collector runs independent, bounded discovery operations for configured bindings.
type Collector struct {
	bindings []Binding
	timeout  time.Duration
	store    *endpointstorage.Store
	mu       sync.Mutex
	sources  map[string]endpointstorage.SourceSnapshot
	revision int64
}

// NewCollector creates a collector and optionally restores source cache from storage.
func NewCollector(ctx context.Context, bindings []Binding, timeout time.Duration, store *endpointstorage.Store) (*Collector, error) {
	if timeout <= 0 {
		return nil, fmt.Errorf("collection timeout must be positive")
	}
	c := &Collector{bindings: append([]Binding(nil), bindings...), timeout: timeout, store: store, sources: make(map[string]endpointstorage.SourceSnapshot)}
	if store != nil {
		items, err := store.ListSourceSnapshots(ctx)
		if err != nil {
			return nil, fmt.Errorf("restore source cache: %w", err)
		}
		for _, item := range items {
			c.sources[item.AdapterID] = item
		}
	}
	return c, nil
}

// Collect executes all bindings independently and returns the latest composite report.
func (c *Collector) Collect(ctx context.Context, observedAtMS int64) (protocol.InventoryReport, error) {
	if observedAtMS < 1 {
		return protocol.InventoryReport{}, fmt.Errorf("observation time must be positive")
	}
	results := make(chan discoveryResult, len(c.bindings))
	for _, binding := range c.bindings {
		binding := binding
		go c.discover(ctx, binding, observedAtMS, results)
	}
	for range c.bindings {
		result := <-results
		c.apply(result, observedAtMS)
	}
	return c.compose(observedAtMS), nil
}

type discoveryResult struct {
	binding Binding
	result  adapter.DiscoverResult
	err     error
	atMS    int64
}

func (c *Collector) discover(parent context.Context, binding Binding, nowMS int64, results chan<- discoveryResult) {
	ctx, cancel := context.WithTimeout(parent, c.timeout)
	defer cancel()
	result, err := binding.Adapter.Discover(ctx, adapter.DiscoverRequest{TimeoutMS: c.timeout.Milliseconds()})
	results <- discoveryResult{binding: binding, result: result, err: err, atMS: nowMS}
}

func (c *Collector) apply(item discoveryResult, nowMS int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	previous, hadPrevious := c.sources[item.binding.AdapterID]
	lastAttemptMS := item.atMS
	if item.result.LastAttemptAtMS > 0 {
		lastAttemptMS = item.result.LastAttemptAtMS
	}
	snapshot := endpointstorage.SourceSnapshot{AdapterID: item.binding.AdapterID, ProviderType: item.binding.ProviderType, DisplayName: item.binding.DisplayName, Version: item.binding.Version, Health: "healthy", Capabilities: item.binding.Capabilities, LastAttemptAtMS: lastAttemptMS}
	if item.err != nil || !item.result.Complete || item.result.CollectionStatus != protocol.CollectionSucceeded {
		snapshot.CollectionStatus = protocol.CollectionFailed
		snapshot.ReportComplete = false
		snapshot.ErrorMessage = "discovery failed"
		if item.err != nil {
			snapshot.ErrorMessage = item.err.Error()
		}
		if item.result.ErrorCode != "" {
			snapshot.ErrorCode = item.result.ErrorCode
		}
		if hadPrevious && previous.DataKnown {
			snapshot.Sessions = previous.Sessions
			snapshot.DataKnown = true
			snapshot.Stale = true
			snapshot.LastSuccessAtMS = previous.LastSuccessAtMS
		} else {
			snapshot.DataKnown = false
			snapshot.Stale = false
		}
	} else {
		snapshot.CollectionStatus = protocol.CollectionSucceeded
		snapshot.ReportComplete = true
		snapshot.Sessions = append([]protocol.Session(nil), item.result.Sessions...)
		if c.store != nil {
			for index := range snapshot.Sessions {
				session := &snapshot.Sessions[index]
				providerKey := session.SessionID
				mapping, lookupErr := c.store.LookupResourceID(context.Background(), providerKey)
				if lookupErr != nil || mapping.AdapterID != item.binding.AdapterID {
					mapping, lookupErr = c.store.GetOrCreateResourceID(context.Background(), item.binding.AdapterID, providerKey, nowMS)
				}
				if lookupErr != nil {
					snapshot.CollectionStatus = protocol.CollectionFailed
					snapshot.ReportComplete = false
					snapshot.DataKnown = false
					snapshot.ErrorCode = "resource_mapping_failed"
					snapshot.ErrorMessage = lookupErr.Error()
					snapshot.Sessions = nil
					break
				}
				session.SessionID = mapping.ResourceID
				if session.AdapterID == "" {
					session.AdapterID = item.binding.AdapterID
				}
			}
		}
		adapterFreshnessProvided := item.result.LastAttemptAtMS > 0 || item.result.LastSuccessAtMS > 0 || item.result.DataKnown || item.result.Stale
		if adapterFreshnessProvided {
			snapshot.DataKnown = item.result.DataKnown
			snapshot.Stale = item.result.Stale
			if item.result.LastSuccessAtMS > 0 {
				lastSuccessMS := item.result.LastSuccessAtMS
				snapshot.LastSuccessAtMS = &lastSuccessMS
			}
		} else {
			snapshot.DataKnown = true
			snapshot.Stale = false
			lastSuccessMS := nowMS
			snapshot.LastSuccessAtMS = &lastSuccessMS
		}
	}
	c.sources[item.binding.AdapterID] = snapshot
	if c.store != nil {
		_ = c.store.ApplySourceSnapshot(context.Background(), snapshot, nowMS)
	}
}
