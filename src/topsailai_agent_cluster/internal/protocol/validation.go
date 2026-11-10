package protocol

import "fmt"

// Validate checks the structural invariants of an inventory report.
func (r InventoryReport) Validate() error {
	if r.SchemaVersion == "" || r.SourceGeneration == "" || r.SnapshotRevision < 1 || r.ObservedAtMS < 1 {
		return fmt.Errorf("inventory identity and revision are required")
	}
	if r.CollectionStatus != CollectionSucceeded && r.CollectionStatus != CollectionPartial && r.CollectionStatus != CollectionFailed && r.CollectionStatus != CollectionUnknown {
		return fmt.Errorf("invalid collection status %q", r.CollectionStatus)
	}
	if !r.ReportComplete && r.CollectionStatus == CollectionSucceeded {
		return fmt.Errorf("successful inventory must be complete")
	}
	seen := make(map[string]struct{}, len(r.Adapters))
	for _, adapter := range r.Adapters {
		if adapter.AdapterID == "" || adapter.ProviderType == "" {
			return fmt.Errorf("adapter identity is required")
		}
		if _, exists := seen[adapter.AdapterID]; exists {
			return fmt.Errorf("duplicate adapter %q", adapter.AdapterID)
		}
		seen[adapter.AdapterID] = struct{}{}
	}
	for _, session := range r.Sessions {
		if session.ClusterSessionID == "" || session.AdapterID == "" {
			return fmt.Errorf("session identity and adapter are required")
		}
		if _, exists := seen[session.AdapterID]; !exists {
			return fmt.Errorf("session references unknown adapter %q", session.AdapterID)
		}
	}
	return nil
}
