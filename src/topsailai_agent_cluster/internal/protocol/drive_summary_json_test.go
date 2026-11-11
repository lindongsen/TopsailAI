package protocol

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestDriveSummaryJSONUsesDrivePID verifies the standard JSON field is emitted and read.
func TestDriveSummaryJSONUsesDrivePID(t *testing.T) {
	data, err := json.Marshal(DriveSummary{DrivePID: 42})
	if err != nil {
		t.Fatalf("marshal drive summary: %v", err)
	}
	if !strings.Contains(string(data), `"drive_pid":42`) || strings.Contains(string(data), `"controller_pid"`) {
		t.Fatalf("JSON = %s, want drive_pid only", data)
	}
	var summary DriveSummary
	if err := json.Unmarshal(data, &summary); err != nil {
		t.Fatalf("unmarshal drive summary: %v", err)
	}
	if summary.DrivePID != 42 {
		t.Fatalf("DrivePID = %d, want 42", summary.DrivePID)
	}
}
