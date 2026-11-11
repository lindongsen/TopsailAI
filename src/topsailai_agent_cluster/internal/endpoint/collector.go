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
//
// The caller's context governs the whole cycle, including the resource-mapping
// store calls. When it is cancelled or its deadline expires the cycle is aborted
// and the context error is returned, so a shutdown never publishes a degraded
// report that describes work the Endpoint had already abandoned.
func (c *Collector) Collect(ctx context.Context, observedAtMS int64) (protocol.InventoryReport, error) {
	if observedAtMS < 1 {
		return protocol.InventoryReport{}, fmt.Errorf("observation time must be positive")
	}
	c.mu.Lock()
	bindings := append([]Binding(nil), c.bindings...)
	c.mu.Unlock()
	results := make(chan discoveryResult, len(bindings))
	for _, binding := range bindings {
		binding := binding
		go c.discover(ctx, binding, observedAtMS, results)
	}
	for range bindings {
		result := <-results
		if err := c.apply(ctx, result, observedAtMS); err != nil {
			// The results channel is buffered for every binding, so the remaining
			// discovery goroutines can still send and exit without a leak.
			return protocol.InventoryReport{}, err
		}
	}
	return c.compose(observedAtMS), nil
}

// RefreshDescriptors re-describes only the selected provider bindings and composes
// a new report from the existing source cache. It never runs provider discovery,
// so session observations retain their original freshness evidence.
func (c *Collector) RefreshDescriptors(ctx context.Context, providerType string, observedAtMS int64) (protocol.InventoryReport, error) {
	if observedAtMS < 1 {
		return protocol.InventoryReport{}, fmt.Errorf("observation time must be positive")
	}
	c.mu.Lock()
	bindings := append([]Binding(nil), c.bindings...)
	c.mu.Unlock()
	type described struct {
		index      int
		descriptor adapter.Descriptor
	}
	updates := make([]described, 0, len(bindings))
	for index, binding := range bindings {
		if providerType != "" && binding.ProviderType != providerType {
			continue
		}
		descriptor, err := binding.Adapter.Describe(ctx)
		if err != nil {
			return protocol.InventoryReport{}, fmt.Errorf("describe adapter %q: %w", binding.AdapterID, err)
		}
		updates = append(updates, described{index: index, descriptor: descriptor})
	}
	if len(updates) == 0 {
		return protocol.InventoryReport{}, fmt.Errorf("no adapter binding matches provider type %q", providerType)
	}
	c.mu.Lock()
	for _, update := range updates {
		binding := &c.bindings[update.index]
		binding.DisplayName = update.descriptor.DisplayName
		binding.Version = update.descriptor.Version
		binding.Capabilities = update.descriptor.Capabilities
		snapshot, ok := c.sources[binding.AdapterID]
		if !ok {
			snapshot = endpointstorage.SourceSnapshot{AdapterID: binding.AdapterID, ProviderType: binding.ProviderType, CollectionStatus: protocol.CollectionUnknown}
		}
		snapshot.DisplayName = binding.DisplayName
		snapshot.Version = binding.Version
		snapshot.Capabilities = binding.Capabilities
		c.sources[binding.AdapterID] = snapshot
	}
	report := c.composeLocked(observedAtMS)
	c.mu.Unlock()
	return report, nil
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

// apply folds one discovery result into the source cache and persists it.
//
// It returns a non-nil error only when the cycle was aborted by its own context.
// A cancelled cycle mutates nothing, so an abandoned collection cannot leave a
// half-applied source behind. A store failure that is not caused by cancellation
// stays a collection failure, because that is a real defect the operator must see.
func (c *Collector) apply(ctx context.Context, item discoveryResult, nowMS int64) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	binding := item.binding
	for _, current := range c.bindings {
		if current.AdapterID == item.binding.AdapterID {
			binding = current
			break
		}
	}
	previous, hadPrevious := c.sources[binding.AdapterID]
	lastAttemptMS := item.atMS
	if item.result.LastAttemptAtMS > 0 {
		lastAttemptMS = item.result.LastAttemptAtMS
	}
	snapshot := endpointstorage.SourceSnapshot{AdapterID: binding.AdapterID, ProviderType: binding.ProviderType, DisplayName: binding.DisplayName, Version: binding.Version, Health: "healthy", Capabilities: binding.Capabilities, LastAttemptAtMS: lastAttemptMS}
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
				clusterSessionID := session.ClusterSessionID
				mapping, lookupErr := c.store.LookupResourceID(ctx, clusterSessionID)
				if lookupErr != nil || mapping.AdapterID != binding.AdapterID {
					mapping, lookupErr = c.store.GetOrCreateResourceID(ctx, binding.AdapterID, clusterSessionID, nowMS)
				}
				if lookupErr != nil {
					// A cancelled store call means the cycle was abandoned, not
					// that the provider returned bad data. Reporting it as a
					// mapping failure would publish a degraded report for work
					// nobody is waiting for any more.
					if ctxErr := ctx.Err(); ctxErr != nil {
						return ctxErr
					}
					snapshot.CollectionStatus = protocol.CollectionFailed
					snapshot.ReportComplete = false
					snapshot.DataKnown = false
					snapshot.ErrorCode = "resource_mapping_failed"
					snapshot.ErrorMessage = lookupErr.Error()
					snapshot.Sessions = nil
					break
				}
				session.ClusterSessionID = mapping.ResourceID
				if session.AdapterID == "" {
					session.AdapterID = binding.AdapterID
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
	// Re-check before mutating the cache so an aborted cycle leaves no trace.
	if err := ctx.Err(); err != nil {
		return err
	}
	c.sources[binding.AdapterID] = snapshot
	if c.store != nil {
		if err := c.store.ApplySourceSnapshot(ctx, snapshot, nowMS); err != nil && ctx.Err() != nil {
			return ctx.Err()
		}
	}
	return nil
}
