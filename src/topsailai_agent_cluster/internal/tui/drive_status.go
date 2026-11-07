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
	EndpointID   string                 `json:"endpoint_id"`
	SessionID    string                 `json:"session_id"`
	Generation   string                 `json:"generation"`
	ObservedAtMS int64                  `json:"observed_at_ms"`
	Drive        *protocol.DriveSummary `json:"drive"`
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
		if session.SessionID != resourceID {
			continue
		}
		view := driveStatusView{EndpointID: endpointID, SessionID: session.SessionID, Generation: session.Generation, ObservedAtMS: session.ObservedAtMS, Drive: session.Drive}
		if jsonMode {
			return RenderJSON(out, view)
		}
		return renderDriveStatus(out, view)
	}
	return fmt.Errorf("session %q was not reported by endpoint %q", resourceID, endpointID)
}

// renderDriveStatus prints the controller summary together with its freshness,
// so an unverified record is never read as a live controller.
func renderDriveStatus(out io.Writer, view driveStatusView) error {
	if view.Drive == nil {
		_, err := fmt.Fprintf(out, "session: %s\ndrive_state: not_reported\ndrive_verified: false\nnote: the provider reported no driver observation; this is not proof that no driver exists\n", view.SessionID)
		return err
	}
	if _, err := fmt.Fprintf(out, "session: %s\ndrive_state: %s\ndrive_verified: %t\ndrive_observed_at_ms: %d\n", view.SessionID, view.Drive.State, view.Drive.Verified, view.Drive.ObservedAtMS); err != nil {
		return err
	}
	if view.Drive.Reason != "" {
		if _, err := fmt.Fprintf(out, "drive_reason: %s\n", view.Drive.Reason); err != nil {
			return err
		}
	}
	if view.Drive.ControllerPID != 0 {
		if _, err := fmt.Fprintf(out, "controller_pid: %d\n", view.Drive.ControllerPID); err != nil {
			return err
		}
	}
	if view.Drive.RunID != "" {
		if _, err := fmt.Fprintf(out, "drive_run_id: %s\n", view.Drive.RunID); err != nil {
			return err
		}
	}
	return nil
}
