package tui

import (
	"bytes"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// renderedTimeValue extracts the value of one labelled time field from a rendered
// human surface. It returns the value and whether the label was present.
//
// Two separators are supported because the CLI has two human layouts: a detail line
// writes "label: value", and a compact row writes tab-separated "label=value" fields.
// Both are read by a human, so both must be assertable on their rendered text rather
// than on the timestamp they were built from.
func renderedTimeValue(output, label string) (string, bool) {
	for _, line := range strings.Split(output, "\n") {
		for _, field := range strings.Split(line, "\t") {
			trimmed := strings.TrimSpace(field)
			if value, ok := strings.CutPrefix(trimmed, label+":"); ok {
				return strings.TrimSpace(value), true
			}
			if value, ok := strings.CutPrefix(trimmed, label+"="); ok {
				return strings.TrimSpace(value), true
			}
		}
	}
	return "", false
}

// assertRenderedInstant proves one rendered time value denotes the expected instant.
//
// The value must parse as a date and clock time, and the parsed instant must equal the
// expected epoch milliseconds. Parsing in the local zone is correct rather than a
// shortcut: the renderers deliberately print an operator's own wall clock, so the
// round trip is the only assertion that holds on every host. A raw epoch number cannot
// satisfy this check, because it does not parse as a date and clock time.
func assertRenderedInstant(t *testing.T, output, label string, wantMS int64) {
	t.Helper()
	value, ok := renderedTimeValue(output, label)
	if !ok {
		t.Fatalf("missing %q line in output: %q", label, output)
	}
	parsed, err := time.ParseInLocation(layoutDateTime, value, time.Local)
	if err != nil {
		t.Fatalf("%s=%q is not a readable date and clock time: %v", label, value, err)
	}
	if got := parsed.UnixMilli(); got != wantMS {
		t.Fatalf("%s=%q denotes %d, want %d", label, value, got, wantMS)
	}
}

// TestTimeFormattersRenderReadableText proves each layout renders a readable value and
// that an unreported time is stated rather than printed as a zero.
func TestTimeFormattersRenderReadableText(t *testing.T) {
	const stamp = int64(1700000000000)
	cases := []struct {
		name   string
		render func(int64, *time.Location) string
		want   string
	}{
		{"clock", formatClockTime, "06:13:20"},
		{"dateTime", formatDateTime, "2023-11-15 06:13:20"},
		{"dateTimeMillis", formatDateTimeMillis, "2023-11-15 06:13:20.000"},
	}
	for _, tc := range cases {
		if got := tc.render(stamp, time.FixedZone("CST", 8*3600)); got != tc.want {
			t.Errorf("%s=%q want=%q", tc.name, got, tc.want)
		}
		if got := tc.render(0, time.UTC); got != unreportedTime {
			t.Errorf("%s(0)=%q want=%q", tc.name, got, unreportedTime)
		}
		if got := tc.render(-1, time.UTC); got != unreportedTime {
			t.Errorf("%s(-1)=%q want=%q", tc.name, got, unreportedTime)
		}
	}
}

// TestHumanSurfacesNeverPrintABareEpochNumber is the regression test for the reported
// defect: every time a human reads must be readable, never a raw millisecond count.
//
// Each surface is rendered with a distinctive stamp, and the assertion fails if that
// number appears anywhere in the output. A distinctive value is used because it cannot
// be confused with a default, a zero or a length.
func TestHumanSurfacesNeverPrintABareEpochNumber(t *testing.T) {
	const stamp = int64(1700000000000)
	const raw = "1700000000000"

	var rows bytes.Buffer
	RenderRows(&rows, []SessionRow{{EndpointID: "e1", State: "idle", LastSuccessAtMS: ptr(stamp)}})
	assertRenderedInstant(t, rows.String(), "last_success_at", stamp)

	var detail bytes.Buffer
	RenderDetail(&detail, Detail{
		Endpoint:  protocol.Endpoint{EndpointID: "e1"},
		Inventory: protocol.InventoryReport{Adapters: []protocol.AdapterSummary{{LastSuccessAtMS: ptr(stamp)}}},
	})
	assertRenderedInstant(t, detail.String(), "last_success_at", stamp)

	var snapshot bytes.Buffer
	RenderSnapshotStyled(&snapshot, stamp, "line", false, 10, ColorPolicy{})
	assertRenderedInstant(t, snapshot.String(), "observed_at", stamp)

	var info bytes.Buffer
	if err := RenderSessionInfo(&info, protocol.Endpoint{EndpointID: "e1"}, protocol.Session{
		ClusterSessionID: "res-1",
		ObservedAtMS:     stamp,
		Drive:            &protocol.DriveSummary{State: "running", ObservedAtMS: stamp},
	}); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	assertRenderedInstant(t, info.String(), "observed_at", stamp)
	assertRenderedInstant(t, info.String(), "drive_observed_at", stamp)

	var drive bytes.Buffer
	if err := renderDriveStatus(&drive, driveStatusView{
		EndpointID:       "e1",
		ClusterSessionID: "res-1",
		Drive:            &protocol.DriveSummary{State: "running", ObservedAtMS: stamp},
	}); err != nil {
		t.Fatalf("renderDriveStatus: %v", err)
	}
	assertRenderedInstant(t, drive.String(), "drive_observed_at", stamp)

	for name, output := range map[string]string{
		"rows":     rows.String(),
		"detail":   detail.String(),
		"snapshot": snapshot.String(),
		"info":     info.String(),
		"drive":    drive.String(),
	} {
		if strings.Contains(output, raw) {
			t.Errorf("%s surface still prints the raw epoch number: %q", name, output)
		}
	}
}

// TestHumanTimeLabelsDoNotClaimMilliseconds proves a human label matches the value it
// introduces. A label ending in _ms promises a millisecond count, so it must not be used
// for a rendered date and clock time.
func TestHumanTimeLabelsDoNotClaimMilliseconds(t *testing.T) {
	var snapshot bytes.Buffer
	RenderSnapshotStyled(&snapshot, 1700000000000, "line", false, 10, ColorPolicy{})
	if strings.Contains(snapshot.String(), "_ms") {
		t.Fatalf("human snapshot label still claims milliseconds: %q", snapshot.String())
	}

	var rows bytes.Buffer
	RenderRows(&rows, []SessionRow{{EndpointID: "e1", LastSuccessAtMS: ptr(1700000000000)}})
	if strings.Contains(rows.String(), "_ms") {
		t.Fatalf("human row label still claims milliseconds: %q", rows.String())
	}
}
