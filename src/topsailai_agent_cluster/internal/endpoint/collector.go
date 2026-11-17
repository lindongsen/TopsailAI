// Package endpoint provides Endpoint-side collection and inventory composition.
package endpoint

import (
	"context"
	"errors"
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
	bindings             []Binding
	timeout              time.Duration
	store                *endpointstorage.Store
	sourceCacheExpiry    time.Duration
	logCacheDeletion     func(string)
	logCollectionFailure func(string, string, string, int64)
	mu                   sync.Mutex
	sources              map[string]endpointstorage.SourceSnapshot
	revision             int64
}

// CollectorOptions controls durable source-cache lifecycle and degraded-cycle reporting.
type CollectorOptions struct {
	SourceCacheExpiry    time.Duration
	LogCacheDeletion     func(string)
	LogCollectionFailure func(adapterID, errorCode, errorMessage string, lastSuccessAtMS int64)
}

// NewCollector creates a collector and restores cache only for configured bindings.
func NewCollector(ctx context.Context, bindings []Binding, timeout time.Duration, store *endpointstorage.Store) (*Collector, error) {
	return NewCollectorWithOptions(ctx, bindings, timeout, store, CollectorOptions{})
}

// NewCollectorWithOptions creates a collector with explicit cache retention.
func NewCollectorWithOptions(ctx context.Context, bindings []Binding, timeout time.Duration, store *endpointstorage.Store, options CollectorOptions) (*Collector, error) {
	if timeout <= 0 {
		return nil, fmt.Errorf("collection timeout must be positive")
	}
	if options.SourceCacheExpiry < 0 {
		return nil, fmt.Errorf("source cache expiry must not be negative")
	}
	configured := make(map[string]struct{}, len(bindings))
	for _, binding := range bindings {
		configured[binding.AdapterID] = struct{}{}
	}
	c := &Collector{bindings: append([]Binding(nil), bindings...), timeout: timeout, store: store, sourceCacheExpiry: options.SourceCacheExpiry, logCacheDeletion: options.LogCacheDeletion, logCollectionFailure: options.LogCollectionFailure, sources: make(map[string]endpointstorage.SourceSnapshot)}
	if store != nil {
		items, err := store.ListSourceSnapshots(ctx)
		if err != nil {
			return nil, fmt.Errorf("restore source cache: %w", err)
		}
		for _, item := range items {
			if _, ok := configured[item.AdapterID]; ok {
				c.sources[item.AdapterID] = item
			}
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
	if err := c.expireSourceCache(ctx, observedAtMS); err != nil {
		return protocol.InventoryReport{}, err
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

// expireSourceCache removes durable and in-memory observations older than the
// configured retention window. A disabled window is used only by tests and
// callers that have not opted into lifecycle management.
func (c *Collector) expireSourceCache(ctx context.Context, observedAtMS int64) error {
	if c.store == nil || c.sourceCacheExpiry == 0 {
		return nil
	}
	cutoffMS := observedAtMS - c.sourceCacheExpiry.Milliseconds()
	if cutoffMS < 1 {
		return nil
	}
	adapterIDs, err := c.store.ExpireSourceSnapshots(ctx, cutoffMS)
	if err != nil {
		return fmt.Errorf("expire source cache: %w", err)
	}
	if len(adapterIDs) == 0 {
		return nil
	}
	c.mu.Lock()
	for _, adapterID := range adapterIDs {
		delete(c.sources, adapterID)
	}
	c.mu.Unlock()
	if c.logCacheDeletion != nil {
		for _, adapterID := range adapterIDs {
			c.logCacheDeletion(adapterID)
		}
	}
	return nil
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
	if errors.Is(item.err, adapter.ErrBusy) {
		// A capacity refusal is not a provider failure: the cycle simply did not
		// run. Keeping the previous snapshot means a local scheduling collision
		// never degrades a healthy inventory, which is what made every operator
		// command refuse with "inventory is unavailable" while the Endpoint was
		// merely busy with its own periodic collection.
		if hadPrevious && previous.DataKnown {
			return nil
		}
		// Nothing was observed yet, so the inventory is unknown rather than
		// complete: publishing an empty complete report would claim the provider
		// holds no sessions when it was never asked.
		snapshot.CollectionStatus = protocol.CollectionUnknown
		snapshot.ReportComplete = false
		snapshot.ErrorMessage = "discovery skipped: adapter capacity unavailable"
		c.sources[binding.AdapterID] = snapshot
		return nil
	}
	if item.err != nil || !item.result.Complete || item.result.CollectionStatus != protocol.CollectionSucceeded {
		snapshot.ReportComplete = false
		snapshot.ErrorMessage = "discovery failed"
		if item.err != nil {
			snapshot.ErrorMessage = item.err.Error()
		}
		if item.result.ErrorCode != "" {
			snapshot.ErrorCode = item.result.ErrorCode
		}
		// A cycle that observed rows but could not complete them is degraded, not
		// failed. Reporting it as failed discarded every healthy row it did observe,
		// so one unattributable provider row made the whole node look broken while
		// every other session was fine. The distinction is load-bearing: `failed`
		// means nothing was observed, `partial` means something was observed and
		// something was not.
		if item.err == nil && len(item.result.Sessions) > 0 {
			snapshot.CollectionStatus = protocol.CollectionPartial
			snapshot.Sessions = append([]protocol.Session(nil), item.result.Sessions...)
			if err := c.mapSessions(ctx, &snapshot, binding, nowMS); err != nil {
				return err
			}
			if snapshot.CollectionStatus != protocol.CollectionFailed {
				snapshot.DataKnown = true
				snapshot.Stale = false
				lastSuccessMS := nowMS
				snapshot.LastSuccessAtMS = &lastSuccessMS
			}
		} else if hadPrevious && previous.DataKnown {
			snapshot.CollectionStatus = protocol.CollectionFailed
			snapshot.Sessions = previous.Sessions
			snapshot.DataKnown = true
			snapshot.Stale = true
			snapshot.LastSuccessAtMS = previous.LastSuccessAtMS
		} else {
			snapshot.CollectionStatus = protocol.CollectionFailed
			snapshot.DataKnown = false
			snapshot.Stale = false
		}
		// The error only lives in the source cache, and the next successful cycle
		// overwrites it. Without this line a transient provider failure leaves no
		// trace anywhere, which is why one recurring failure stayed undiagnosed.
		if c.logCollectionFailure != nil {
			lastSuccessMS := int64(0)
			if snapshot.LastSuccessAtMS != nil {
				lastSuccessMS = *snapshot.LastSuccessAtMS
			}
			c.logCollectionFailure(binding.AdapterID, snapshot.ErrorCode, snapshot.ErrorMessage, lastSuccessMS)
		}
	} else {
		snapshot.CollectionStatus = protocol.CollectionSucceeded
		snapshot.ReportComplete = true
		snapshot.Sessions = append([]protocol.Session(nil), item.result.Sessions...)
		if err := c.mapSessions(ctx, &snapshot, binding, nowMS); err != nil {
			return err
		}
		// A cycle that withheld every reported row is not a success, so it must
		// not claim fresh known data. mapSessions downgrades that case to failed;
		// assigning freshness here would overwrite the downgrade and make an
		// empty report read as "known, and there are no sessions".
		if snapshot.CollectionStatus != protocol.CollectionFailed {
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

// mapSessions replaces each session's provider key with its durable Cluster ID.
//
// It is shared by the complete and the degraded branches so the mapping rule
// exists once. A second copy would drift, and the drift would be invisible: both
// copies would compile and both would produce plausible IDs.
//
// A store failure that is not caused by cancellation marks the snapshot failed and
// clears its sessions, because publishing rows whose Cluster IDs were never minted
// would expose identities no later command could resolve. A cancelled store call
// returns the context error instead, because that cycle was abandoned rather than
// observing bad data.
func (c *Collector) mapSessions(ctx context.Context, snapshot *endpointstorage.SourceSnapshot, binding Binding, nowMS int64) error {
	if c.store == nil {
		return nil
	}
	mapped := snapshot.Sessions[:0]
	for index := range snapshot.Sessions {
		session := snapshot.Sessions[index]
		clusterSessionID := session.ClusterSessionID
		mapping, lookupErr := c.store.LookupResourceID(ctx, clusterSessionID)
		if lookupErr != nil || mapping.AdapterID != binding.AdapterID || mapping.ResourceKind != protocol.ResourceSession {
			switch {
			case lookupErr != nil && !errors.Is(lookupErr, endpointstorage.ErrResourceNotFound):
				// A genuine store failure is not a mapping decision, so it is
				// reported as-is instead of being reinterpreted as one.
			case protocol.IsClusterResourceID(clusterSessionID):
				// The value already has the shape of a Cluster resource ID, so
				// it is not a provider key and must not be used as one. Minting
				// here would store a mapping row keyed by a Cluster ID, which
				// makes the provider-to-cluster relationship ambiguous: a later
				// reconciliation reading the table could not tell the two kinds
				// of key apart. It would also hand the session a different
				// Cluster ID than the one the adapter minted, silently breaking
				// identity stability. The adapter mints before it reports, so
				// this is an adapter contract violation: the row is withheld and
				// the rest of the cycle is preserved, because one bad row must
				// not discard every healthy row the provider did report.
				snapshot.CollectionStatus = protocol.CollectionPartial
				snapshot.ReportComplete = false
				snapshot.ErrorCode = "resource_mapping_failed"
				snapshot.ErrorMessage = fmt.Sprintf("session reports Cluster resource ID %q that is not a %s mapping for adapter %q", clusterSessionID, protocol.ResourceSession, binding.AdapterID)
				continue
			default:
				mapping, lookupErr = c.store.GetOrCreateResourceID(ctx, binding.AdapterID, protocol.ResourceSession, clusterSessionID, nowMS)
			}
		}
		if lookupErr != nil {
			if ctxErr := ctx.Err(); ctxErr != nil {
				return ctxErr
			}
			snapshot.CollectionStatus = protocol.CollectionFailed
			snapshot.ReportComplete = false
			snapshot.DataKnown = false
			snapshot.ErrorCode = "resource_mapping_failed"
			snapshot.ErrorMessage = lookupErr.Error()
			snapshot.Sessions = nil
			return nil
		}
		session.ClusterSessionID = mapping.ResourceID
		if session.AdapterID == "" {
			session.AdapterID = binding.AdapterID
		}
		mapped = append(mapped, session)
	}
	snapshot.Sessions = mapped
	if len(mapped) == 0 && snapshot.CollectionStatus == protocol.CollectionPartial {
		// Every reported row was withheld, so nothing was actually observed.
		// Publishing `partial` with an empty list would read as "known, and there
		// are no sessions", which would make the existing rows disappear from the
		// operator's view. `failed` is the honest status: nothing usable was
		// observed, and the previous snapshot is retained by the caller.
		snapshot.CollectionStatus = protocol.CollectionFailed
		snapshot.DataKnown = false
	}
	return nil
}
