package tui

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/protocol"
)

// driveStatusView is the read projection of one session's controller summary.
// It carries the endpoint and session identity so a JSON caller never has to
// correlate the answer with the request it sent.
type driveStatusView struct {
	EndpointID         string                 `json:"endpoint_id"`
	ClusterSessionID   string                 `json:"cluster_session_id"`
	ProviderGeneration string                 `json:"provider_generation"`
	ObservedAtMS       int64                  `json:"observed_at_ms"`
	Drive              *protocol.DriveSummary `json:"drive"`
}

// DriveStatus renders the standard drive summary of one session from the
// persisted inventory. It is a read projection: it never probes the provider and
// never admits a command, so an unverified record is never presented as a live
// controller. A missing summary is reported as not observed rather than as an
// empty or stopped controller, because the provider simply reported nothing.
func (r CommandRunner) DriveStatus(ctx context.Context, out io.Writer, endpointID, resourceID string, jsonMode bool) error {
	report, err := r.API.GetInventory(ctx, endpointID)
	if err != nil {
		return err
	}
	if !report.ReportComplete {
		return fmt.Errorf("endpoint %q inventory is incomplete; drive state is unknown", endpointID)
	}
	for _, session := range report.Sessions {
		if session.ClusterSessionID != resourceID {
			continue
		}
		view := driveStatusView{EndpointID: endpointID, ClusterSessionID: session.ClusterSessionID, ProviderGeneration: session.ProviderGeneration, ObservedAtMS: session.ObservedAtMS, Drive: session.Drive}
		if jsonMode {
			return RenderJSON(out, view)
		}
		return renderDriveStatus(out, view)
	}
	return fmt.Errorf("session %q was not reported by endpoint %q", resourceID, endpointID)
}

// detailLine is one label/value pair of a human-readable detail render.
type detailLine struct {
	label string
	value string
}

// driveDetailLines returns the drive fields of one session as label/value pairs.
//
// It is the single source of the drive detail, so info and drive status cannot
// drift apart. The session identity is not included, because each caller already
// prints it in its own form. Values are returned raw: each caller applies its own
// escaping policy, because the two surfaces have different output boundaries.
func driveDetailLines(drive *protocol.DriveSummary) []detailLine {
	if drive == nil {
		return []detailLine{
			{"drive_state", "not_reported"},
			{"drive_verified", "false"},
			{"note", "the provider reported no driver observation; this is not proof that no driver exists"},
		}
	}
	lines := []detailLine{
		{"drive_state", drive.State},
		{"drive_verified", fmt.Sprint(drive.Verified)},
		{"drive_observed_at", formatDateTime(drive.ObservedAtMS, nil)},
	}
	if drive.Reason != "" {
		lines = append(lines, detailLine{"drive_reason", drive.Reason})
	}
	if drive.ControllerPID != 0 {
		lines = append(lines, detailLine{"controller_pid", fmt.Sprint(drive.ControllerPID)})
	}
	if drive.RunID != "" {
		lines = append(lines, detailLine{"drive_run_id", drive.RunID})
	}
	return lines
}

// renderDriveStatus prints the controller summary together with its freshness,
// so an unverified record is never read as a live controller.
func renderDriveStatus(out io.Writer, view driveStatusView) error {
	if _, err := fmt.Fprintf(out, "session: %s\n", view.ClusterSessionID); err != nil {
		return err
	}
	for _, line := range driveDetailLines(view.Drive) {
		if _, err := fmt.Fprintf(out, "%s: %s\n", line.label, line.value); err != nil {
			return err
		}
	}
	return nil
}
