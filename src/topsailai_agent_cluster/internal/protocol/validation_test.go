package protocol

import "testing"

func validInventory() InventoryReport {
	return InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 1, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: CollectionSucceeded, Adapters: []AdapterSummary{{AdapterID: "a1", ProviderType: "test", DataKnown: true}}, Sessions: []Session{{ClusterSessionID: "s1", AdapterID: "a1"}}}
}

func TestInventoryValidation(t *testing.T) {
	if err := validInventory().Validate(); err != nil {
		t.Fatalf("valid inventory rejected: %v", err)
	}
	cases := []InventoryReport{
		func() InventoryReport { r := validInventory(); r.Adapters[0].AdapterID = ""; return r }(),
		func() InventoryReport { r := validInventory(); r.Sessions[0].AdapterID = "missing"; return r }(),
		func() InventoryReport {
			r := validInventory()
			r.Adapters = append(r.Adapters, r.Adapters[0])
			return r
		}(),
		func() InventoryReport { r := validInventory(); r.ReportComplete = false; return r }(),
	}
	for _, report := range cases {
		if err := report.Validate(); err == nil {
			t.Errorf("invalid inventory accepted: %+v", report)
		}
	}
}
