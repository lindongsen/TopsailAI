package tui

import (
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestDriveCellProjectsEveryStandardState pins the table projection of the
// controller summary. The projection must never upgrade an unverified record to
// a running controller, and must never turn an absent observation into a
// confirmed absence.
func TestDriveCellProjectsEveryStandardState(t *testing.T) {
	for _, tc := range []struct {
		name string
		row  SessionRow
		want string
	}{
		{
			name: "absent observation is not a confirmed absence",
			row:  SessionRow{},
			want: "-",
		},
		{
			name: "verified running stays running",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true}},
			want: "running",
		},
		{
			name: "unverified running is never presented as running",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: false}},
			want: "unverified",
		},
		{
			name: "reported none is a confirmed absence",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateNone}},
			want: "none",
		},
		{
			name: "stale record keeps its own state",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateStale}},
			want: "stale",
		},
		{
			name: "exited record keeps its own state",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateExited}},
			want: "exited",
		},
		{
			name: "failed record keeps its own state",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateFailed}},
			want: "failed",
		},
		{
			name: "reported unknown keeps its own state",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateUnknown}},
			want: "unknown",
		},
		{
			name: "empty state is unknown rather than blank",
			row:  SessionRow{Drive: &protocol.DriveSummary{}},
			want: "unknown",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := driveCell(tc.row); got != tc.want {
				t.Fatalf("driveCell=%q want=%q", got, tc.want)
			}
		})
	}
}

// TestDriveCellEscapesProviderText proves the projection is rendered through the
// same escaping as every other cell, so a provider value cannot inject terminal
// control sequences into the table.
func TestDriveCellEscapesProviderText(t *testing.T) {
	row := SessionRow{Drive: &protocol.DriveSummary{State: "run\x1b[31mning"}}
	cells := tableCells(row, time.UTC)
	if got := cells[columnDrive]; strings.Contains(got, "\x1b") {
		t.Fatalf("drive cell kept a control sequence: %q", got)
	}
}

// TestDriveColumnFollowsSessionID pins the column position. The column must sit
// directly after SESSION_ID, so the controller state is read next to the session
// identity it belongs to.
func TestDriveColumnFollowsSessionID(t *testing.T) {
	index := -1
	for position, column := range allColumns {
		if column.key == columnDrive {
			index = position
		}
	}
	if index < 0 {
		t.Fatal("drive column is missing from allColumns")
	}
	if allColumns[index-1].key != columnID {
		t.Fatalf("drive column follows %q, want %q", allColumns[index-1].key, columnID)
	}
	if allColumns[index].header != "DRIVER" {
		t.Fatalf("drive header=%q want=DRIVER", allColumns[index].header)
	}
}

// TestDriveColumnRendersInTable proves the column reaches the rendered table and
// that an absent observation renders as a dash rather than an empty cell.
func TestDriveColumnRendersInTable(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_2", ProviderSessionID: "provider-session-2", State: "running", CollectionStatus: protocol.CollectionSucceeded, Drive: &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true}},
	}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	headerCells := strings.Split(lines[1], " │ ")
	driveIndex := -1
	for position, cell := range headerCells {
		if strings.TrimSpace(cell) == "DRIVER" {
			driveIndex = position
		}
	}
	if driveIndex < 0 {
		t.Fatalf("rendered header has no DRIVER column: %q", lines[1])
	}
	absent := strings.Split(lines[3], " │ ")
	if got := strings.TrimSpace(absent[driveIndex]); got != "-" {
		t.Fatalf("absent drive cell=%q want=-", got)
	}
	present := strings.Split(lines[4], " │ ")
	if got := strings.TrimSpace(present[driveIndex]); got != "running" {
		t.Fatalf("verified drive cell=%q want=running", got)
	}
}

// renderDriveRow renders one row and returns the output, so a colour assertion
// cannot be confused with styling produced by another row.
func renderDriveRow(t *testing.T, row SessionRow, color ColorPolicy) string {
	t.Helper()
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, []SessionRow{row}, nil, TableOptions{Location: time.UTC, Color: color}); err != nil {
		t.Fatalf("RenderTable: %v", err)
	}
	return out.String()
}

// TestDriveCellEmphasisesOnlyVerifiedRunning proves the emphasis means exactly
// "a controller is running right now". Every other state must stay unemphasised,
// because a bold green cell reads as a live controller and would make an
// unverified, stale, exited or failed record look healthy.
func TestDriveCellEmphasisesOnlyVerifiedRunning(t *testing.T) {
	cases := []struct {
		name string
		row  SessionRow
		want bool
	}{
		{
			name: "verified running is emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true}},
			want: true,
		},
		{
			name: "unverified running is never emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: false}},
			want: false,
		},
		{
			name: "stale record is never emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateStale}},
			want: false,
		},
		{
			name: "exited record is never emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateExited}},
			want: false,
		},
		{
			name: "failed record is never emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateFailed}},
			want: false,
		},
		{
			name: "reported none is never emphasised",
			row:  SessionRow{Drive: &protocol.DriveSummary{State: protocol.DriveStateNone}},
			want: false,
		},
		{
			name: "absent observation is never emphasised",
			row:  SessionRow{},
			want: false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			tc.row.EndpointID = "endpoint-1"
			tc.row.EndpointLabel = "host-1"
			tc.row.ClusterSessionID = "res_1"
			tc.row.State = "running"
			tc.row.CollectionStatus = protocol.CollectionSucceeded
			rendered := renderDriveRow(t, tc.row, ColorPolicy{Enabled: true})
			got := strings.Contains(rendered, ansiBoldGreen)
			if got != tc.want {
				t.Fatalf("bold green present=%t want=%t output=%q", got, tc.want, rendered)
			}
		})
	}
}

// TestDriveEmphasisDoesNotRecolourTheRow proves the emphasis is confined to the
// DRIVER cell. The row colour still reports the session state, so a controller
// can never make one cell contradict the row it belongs to.
func TestDriveEmphasisDoesNotRecolourTheRow(t *testing.T) {
	row := SessionRow{
		EndpointID:       "endpoint-1",
		EndpointLabel:    "host-1",
		ClusterSessionID: "res_1",
		State:            "running",
		CollectionStatus: protocol.CollectionSucceeded,
		Drive:            &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true},
	}
	rendered := renderDriveRow(t, row, ColorPolicy{Enabled: true})
	// The NO cell keeps the plain green row colour, so the row is still reported
	// as a running session rather than being recoloured for the controller.
	if !strings.Contains(rendered, ansiGreen+"1 ") {
		t.Fatalf("row colour lost from the NO cell: %q", rendered)
	}
	if !strings.Contains(rendered, ansiBoldGreen+"running") {
		t.Fatalf("drive cell is not emphasised: %q", rendered)
	}
}

// TestDriveEmphasisIsAbsentWithoutColour proves the emphasis is presentation
// only. A plain terminal, a redirected stream and a dumb terminal must still
// carry the drive state as text, so the signal never depends on colour support.
func TestDriveEmphasisIsAbsentWithoutColour(t *testing.T) {
	row := SessionRow{
		EndpointID:       "endpoint-1",
		EndpointLabel:    "host-1",
		ClusterSessionID: "res_1",
		State:            "running",
		CollectionStatus: protocol.CollectionSucceeded,
		Drive:            &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true},
	}
	rendered := renderDriveRow(t, row, ColorPolicy{})
	if strings.Contains(rendered, "\x1b") {
		t.Fatalf("plain output contains ANSI: %q", rendered)
	}
	if !strings.Contains(rendered, "running") {
		t.Fatalf("drive state lost without colour: %q", rendered)
	}
}

// TestDriveEmphasisSurvivesNarrowLayout proves the narrow layout emphasises the
// same cell. Both layouts share one state projection, so a terminal width must
// never change which fact is emphasised.
func TestDriveEmphasisSurvivesNarrowLayout(t *testing.T) {
	row := SessionRow{
		EndpointID:       "endpoint-1",
		EndpointLabel:    "host-1",
		ClusterSessionID: "res_1",
		State:            "running",
		CollectionStatus: protocol.CollectionSucceeded,
		Drive:            &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true},
	}
	var out, errors strings.Builder
	if err := RenderTable(&out, &errors, []SessionRow{row}, nil, TableOptions{Width: 40, Location: time.UTC, Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatalf("RenderTable: %v", err)
	}
	if !strings.Contains(out.String(), ansiBoldGreen) {
		t.Fatalf("narrow layout lost the emphasis: %q", out.String())
	}
}
