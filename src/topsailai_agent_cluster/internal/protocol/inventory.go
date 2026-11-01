package protocol

// InventoryReport is the complete latest report for one Endpoint.
type InventoryReport struct {
	SchemaVersion    string           `json:"schema_version"`
	SourceGeneration string           `json:"source_generation"`
	SnapshotRevision int64            `json:"snapshot_revision"`
	ObservedAtMS     int64            `json:"observed_at_ms"`
	ReportComplete   bool             `json:"report_complete"`
	CollectionStatus string           `json:"collection_status"`
	Adapters         []AdapterSummary `json:"adapters"`
	Sessions         []Session        `json:"sessions"`
}

// CollectionStatus values describe observation availability.
const (
	CollectionSucceeded = "succeeded"
	CollectionPartial   = "partial"
	CollectionFailed    = "failed"
	CollectionUnknown   = "unknown"
)
