package endpoint

import (
	"fmt"
	"sort"

	"topsailai_agent_cluster/internal/protocol"
)

func (c *Collector) compose(observedAtMS int64) protocol.InventoryReport {
	c.mu.Lock()
	defer c.mu.Unlock()
	ids := make([]string, 0, len(c.sources))
	for id := range c.sources {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", ObservedAtMS: observedAtMS}
	allSucceeded := true
	hasKnown := false
	for _, id := range ids {
		source := c.sources[id]
		report.Adapters = append(report.Adapters, protocol.AdapterSummary{AdapterID: source.AdapterID, ProviderType: source.ProviderType, DisplayName: source.DisplayName, Version: source.Version, Health: source.Health, Capabilities: source.Capabilities, CollectionStatus: source.CollectionStatus, LastAttemptAtMS: source.LastAttemptAtMS, LastSuccessAtMS: source.LastSuccessAtMS, DataKnown: source.DataKnown, Stale: source.Stale})
		if source.DataKnown {
			hasKnown = true
			for _, session := range source.Sessions {
				if session.AdapterID == "" {
					session.AdapterID = source.AdapterID
				}
				report.Sessions = append(report.Sessions, session)
			}
		}
		if source.CollectionStatus != protocol.CollectionSucceeded || !source.ReportComplete {
			allSucceeded = false
		}
	}
	report.SnapshotRevision = c.revision + 1
	c.revision = report.SnapshotRevision
	report.ReportComplete = allSucceeded
	switch {
	case allSucceeded:
		report.CollectionStatus = protocol.CollectionSucceeded
	case hasKnown:
		report.CollectionStatus = protocol.CollectionPartial
	case len(ids) == 0:
		report.CollectionStatus = protocol.CollectionSucceeded
	default:
		report.CollectionStatus = protocol.CollectionUnknown
	}
	return report
}

// ValidateReport checks the composed report before publication.
func ValidateReport(report protocol.InventoryReport) error {
	if err := report.Validate(); err != nil {
		return fmt.Errorf("validate composed inventory: %w", err)
	}
	return nil
}
