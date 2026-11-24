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
//
// The identifier is resolved in two namespaces, because the help entry advertises
// both and the interactive surface already accepts both. A cluster resource ID
// keeps precedence, matching findInfoSession: the resource ID is the routing
// identity, so it must win when the two namespaces collide. A provider session ID
// is accepted as the fallback, because an operator reading a provider record has
// that identifier and not the cluster one. Several matches inside one endpoint are
// an error rather than an arbitrary pick, because one provider session can own
// several rows and silently choosing one would report a different row's controller.
func (r CommandRunner) DriveStatus(ctx context.Context, out io.Writer, endpointID, resourceID string, jsonMode bool) error {
	report, err := r.API.GetInventory(ctx, endpointID)
	if err != nil {
		return err
	}
	if !report.ReportComplete {
		return fmt.Errorf("endpoint %q inventory is incomplete; drive state is unknown", endpointID)
	}
	session, err := resolveDriveSession(report.Sessions, resourceID, endpointID)
	if err != nil {
		return err
	}
	view := driveStatusView{EndpointID: endpointID, ClusterSessionID: session.ClusterSessionID, ProviderGeneration: session.ProviderGeneration, ObservedAtMS: session.ObservedAtMS, Drive: session.Drive}
	if jsonMode {
		return RenderJSON(out, view)
	}
	return renderDriveStatus(out, view)
}

// resolveDriveSession resolves one identifier against one endpoint's reported
// sessions. The cluster resource ID namespace is searched first and the provider
// session ID namespace second, so the routing identity always wins a collision.
// The endpoint is a parameter rather than a caller-side wrapper because every
// message names it, and a wrapper would have to restate the sentence around an
// error it does not understand.
func resolveDriveSession(sessions []protocol.Session, id, endpointID string) (protocol.Session, error) {
	if session, matches := matchDriveSession(sessions, id, true); matches > 0 {
		if matches > 1 {
			return protocol.Session{}, fmt.Errorf("resource ID %q matches %d sessions on endpoint %q; use the provider session ID to select one", id, matches, endpointID)
		}
		return session, nil
	}
	if session, matches := matchDriveSession(sessions, id, false); matches > 0 {
		if matches > 1 {
			return protocol.Session{}, fmt.Errorf("provider session %q matches %d sessions on endpoint %q; use the cluster resource ID to select one", id, matches, endpointID)
		}
		return session, nil
	}
	return protocol.Session{}, fmt.Errorf("session %q was not reported by endpoint %q", id, endpointID)
}

// matchDriveSession counts matches in one identifier namespace and returns the
// first one. byResourceID selects the cluster resource ID namespace; otherwise the
// provider session ID namespace is searched. An empty provider session ID never
// matches, because an unverified row carries no identifier to match against.
func matchDriveSession(sessions []protocol.Session, id string, byResourceID bool) (protocol.Session, int) {
	var (
		found   protocol.Session
		matches int
	)
	for _, session := range sessions {
		matched := session.ClusterSessionID == id
		if !byResourceID {
			matched = session.ProviderSessionID != "" && session.ProviderSessionID == id
		}
		if !matched {
			continue
		}
		if matches == 0 {
			found = session
		}
		matches++
	}
	return found, matches
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
	if drive.DrivePID != 0 {
		lines = append(lines, detailLine{"drive_pid", fmt.Sprint(drive.DrivePID)})
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
