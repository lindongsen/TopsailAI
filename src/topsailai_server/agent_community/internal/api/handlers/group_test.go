// Package handlers provides group handler tests.
package handlers

import (
	"testing"
	"time"
)

// TestParseTimeRangeValid verifies valid time range parsing.
func TestParseTimeRangeValid(t *testing.T) {
	start, end, err := parseTimeRange("1000-2000")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if start != 1000 {
		t.Errorf("start = %d, want 1000", start)
	}
	if end != 2000 {
		t.Errorf("end = %d, want 2000", end)
	}
}

// TestParseTimeRangeEmpty verifies empty string returns error.
func TestParseTimeRangeEmpty(t *testing.T) {
	_, _, err := parseTimeRange("")
	if err == nil {
		t.Error("expected error for empty string")
	}
}

// TestParseTimeRangeInvalidFormat verifies error on invalid format.
func TestParseTimeRangeInvalidFormat(t *testing.T) {
	_, _, err := parseTimeRange("invalid")
	if err == nil {
		t.Error("expected error for invalid format")
	}
}

// TestParseTimeRangeInvalidStart verifies error on non-numeric start.
func TestParseTimeRangeInvalidStart(t *testing.T) {
	_, _, err := parseTimeRange("abc-2000")
	if err == nil {
		t.Error("expected error for non-numeric start")
	}
}

// TestParseTimeRangeInvalidEnd verifies error on non-numeric end.
func TestParseTimeRangeInvalidEnd(t *testing.T) {
	_, _, err := parseTimeRange("1000-xyz")
	if err == nil {
		t.Error("expected error for non-numeric end")
	}
}

// TestParseTimeRangeNegativeValues verifies error on negative values.
func TestParseTimeRangeNegativeValues(t *testing.T) {
	_, _, err := parseTimeRange("-1000-2000")
	if err == nil {
		t.Error("expected error for negative start value")
	}

	_, _, err = parseTimeRange("1000--2000")
	if err == nil {
		t.Error("expected error for negative end value")
	}
}

// TestParseTimeRangeSingleValue verifies error on single value.
func TestParseTimeRangeSingleValue(t *testing.T) {
	_, _, err := parseTimeRange("1000")
	if err == nil {
		t.Error("expected error for single value")
	}
}

// TestParseTimeRangeExtraParts verifies error on extra parts.
func TestParseTimeRangeExtraParts(t *testing.T) {
	_, _, err := parseTimeRange("1000-2000-3000")
	if err == nil {
		t.Error("expected error for extra parts")
	}
}

// TestParseTimeRangeStartGreaterThanEnd verifies start > end is allowed (just a range).
func TestParseTimeRangeStartGreaterThanEnd(t *testing.T) {
	start, end, err := parseTimeRange("2000-1000")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if start != 2000 {
		t.Errorf("start = %d, want 2000", start)
	}
	if end != 1000 {
		t.Errorf("end = %d, want 1000", end)
	}
}

// TestGroupResponseStructure verifies group response structure.
func TestGroupResponseStructure(t *testing.T) {
	now := time.Now().UnixMilli()
	resp := GroupResponse{
		GroupID:      "g1",
		GroupName:    "Test Group",
		GroupContext: "Test context",
		GroupKey:     "hashed_key",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}

	if resp.GroupID != "g1" {
		t.Errorf("group_id = %v", resp.GroupID)
	}
	if resp.GroupName != "Test Group" {
		t.Errorf("group_name = %v", resp.GroupName)
	}
	if resp.GroupContext != "Test context" {
		t.Errorf("group_context = %v", resp.GroupContext)
	}
	if resp.GroupKey != "hashed_key" {
		t.Errorf("group_key = %v", resp.GroupKey)
	}
	if resp.CreateAtMs != now {
		t.Errorf("create_at_ms = %d", resp.CreateAtMs)
	}
	if resp.UpdateAtMs != now {
		t.Errorf("update_at_ms = %d", resp.UpdateAtMs)
	}
}

// TestGroupListResponseStructure verifies group list response structure.
func TestGroupListResponseStructure(t *testing.T) {
	resp := ListGroupsResponse{
		Total: 2,
		Items: []GroupResponse{
			{GroupID: "g1", GroupName: "Group 1"},
			{GroupID: "g2", GroupName: "Group 2"},
		},
	}

	if resp.Total != 2 {
		t.Errorf("total = %d, want 2", resp.Total)
	}
	if len(resp.Items) != 2 {
		t.Errorf("items length = %d, want 2", len(resp.Items))
	}
	if resp.Items[0].GroupID != "g1" {
		t.Errorf("first item group_id = %v", resp.Items[0].GroupID)
	}
	if resp.Items[1].GroupID != "g2" {
		t.Errorf("second item group_id = %v", resp.Items[1].GroupID)
	}
}

// TestCreateGroupRequestStructure verifies create group request structure.
func TestCreateGroupRequestStructure(t *testing.T) {
	req := CreateGroupRequest{
		GroupName:    "New Group",
		GroupContext: "Group context",
		GroupKey:     "secret_key",
	}

	if req.GroupName != "New Group" {
		t.Errorf("group_name = %v", req.GroupName)
	}
	if req.GroupContext != "Group context" {
		t.Errorf("group_context = %v", req.GroupContext)
	}
	if req.GroupKey != "secret_key" {
		t.Errorf("group_key = %v", req.GroupKey)
	}
}

// TestUpdateGroupRequestStructure verifies update group request structure.
func TestUpdateGroupRequestStructure(t *testing.T) {
	req := UpdateGroupRequest{
		GroupName:    "Updated Group",
		GroupContext: "Updated context",
	}

	if req.GroupName != "Updated Group" {
		t.Errorf("group_name = %v", req.GroupName)
	}
	if req.GroupContext != "Updated context" {
		t.Errorf("group_context = %v", req.GroupContext)
	}
}
