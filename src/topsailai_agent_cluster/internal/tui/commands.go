package tui

import (
	"context"
	"fmt"
	"io"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// CommandAPI is the shared authenticated API surface used by CLI and REPL commands.
type CommandAPI interface {
	ListEndpoints(context.Context) ([]protocol.Endpoint, error)
	GetInventory(context.Context, string) (protocol.InventoryReport, error)
	GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error)
	GetCommand(context.Context, string) (map[string]any, error)
	ListCommands(context.Context, string, string, int) ([]map[string]any, error)
	GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error)
	AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error)
}

// InteractiveAPI remains an alias for callers compiled against the original REPL seam.
type InteractiveAPI = CommandAPI

// CommandPolicy selects compatibility behavior without changing command semantics.
type CommandPolicy int

const (
	LegacyPolicy CommandPolicy = iota
	InteractivePolicy
)

// CommandRunner executes provider-neutral read commands for both CLI entry points.
type CommandRunner struct {
	API    CommandAPI
	Now    func() time.Time
	NewID  func() string
	Policy CommandPolicy
}

// List executes the shared endpoint inventory query and renderer.
func (r CommandRunner) List(ctx context.Context, out io.Writer, filter string, jsonMode bool) error {
	return r.ListWithOptions(ctx, out, io.Discard, filter, jsonMode, TableOptions{})
}

// ListWithOptions renders text list output through the shared table renderer.
//
// The load is list-scoped rather than the shared target-resolution load, because
// list is the only surface whose default is to omit an endpoint that is not
// online. A target resolver must keep reading a disconnected endpoint's retained
// document, so it keeps calling loadReports.
func (r CommandRunner) ListWithOptions(ctx context.Context, out, errors io.Writer, filter string, jsonMode bool, options TableOptions) error {
	loaded, err := loadListReports(ctx, r.API, filter, options.All)
	if err != nil {
		return err
	}
	return renderListRows(out, errors, loaded, filter, jsonMode, options)
}

// renderListRows renders one already loaded inventory set, so a caller that
// validated the same load does not repeat the API round trip.
func renderListRows(out, errors io.Writer, loaded reportLoad, filter string, jsonMode bool, options TableOptions) error {
	rows := ListRows(loaded.endpoints, loaded.reports, filter)
	// A skipped endpoint was never queried, so it has no observation to render.
	// ListRows still builds a placeholder for it, because that function cannot know
	// which endpoints the loader chose to skip, so the rows are dropped here. This
	// is the second half of one decision: the loader avoids the request, and the
	// renderer avoids the row that request would have produced.
	if len(loaded.skippedOffline) > 0 {
		kept := rows[:0]
		for _, row := range rows {
			if loaded.skippedOffline[row.EndpointID] {
				continue
			}
			kept = append(kept, row)
		}
		rows = kept
	}
	if options.Clean {
		// An endpoint that is not online has stopped reporting, so its retained
		// inventory is historical rather than current. Omitting it is the same
		// decision as omitting a failed fetch, because both are endpoints that
		// failed to report, which is exactly what --clean promises to hide. A
		// fetch failure alone was not enough: a disconnected endpoint still
		// serves its last committed document, so it never produced an error and
		// its stale rows survived the flag.
		//
		// The filter runs before the JSON branch because a flag that is accepted
		// and then silently ignored is worse than a flag that is rejected: a JSON
		// caller would receive rows the table surface had already dropped, and
		// nothing in the output would say the two disagreed.
		offline := make(map[string]bool, len(loaded.endpoints))
		for _, endpoint := range loaded.endpoints {
			if endpoint.ConnectionState != "" && endpoint.ConnectionState != "online" {
				offline[endpoint.EndpointID] = true
			}
		}
		filtered := rows[:0]
		for _, row := range rows {
			if _, failed := loaded.errors[row.EndpointID]; failed {
				continue
			}
			if offline[row.EndpointID] {
				continue
			}
			filtered = append(filtered, row)
		}
		rows = filtered
	}
	if jsonMode {
		return RenderJSON(out, rows)
	}
	assignRowNumbers(rows)
	if options.OnRows != nil {
		options.OnRows(append([]SessionRow(nil), rows...))
	}
	failures := make([]EndpointFailure, 0, len(loaded.errors))
	for endpointID, fetchErr := range loaded.errors {
		failures = append(failures, EndpointFailure{EndpointID: endpointID, Err: fetchErr})
	}
	if err := RenderTable(out, errors, rows, failures, options); err != nil {
		return err
	}
	return writeSkippedOfflineSummary(out, len(loaded.skippedOffline))
}

// writeSkippedOfflineSummary states once that endpoints were omitted, because a
// hidden endpoint must never look like an endpoint that reported no sessions. The
// count is printed instead of the identifiers: naming each one would reproduce the
// per-endpoint noise the skip exists to remove, and --all is the documented way to
// see them. A redirected stream receives the line too, because it is part of the
// answer rather than a diagnostic.
func writeSkippedOfflineSummary(out io.Writer, skipped int) error {
	if skipped == 0 {
		return nil
	}
	_, err := fmt.Fprintf(out, "offline endpoints hidden: %d (use --all to include)\n", skipped)
	return err
}

// Show executes the shared endpoint and session detail query.
func (r CommandRunner) Show(ctx context.Context, out io.Writer, id string, jsonMode bool) error {
	endpoints, err := r.API.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	reports := make(map[string]protocol.InventoryReport, len(endpoints))
	for _, endpoint := range endpoints {
		report, fetchErr := r.API.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr == nil {
			reports[endpoint.EndpointID] = report
		}
	}
	endpoint, report, session, err := FindSession(id, endpoints, reports)
	if err != nil {
		// FindSession can only match an endpoint that has a committed document,
		// and a degraded endpoint has none, so a degraded target would otherwise
		// be reported as absent. The record still exists and carries the deletion
		// date, so the accurate answer is the degraded state itself.
		if degraded, ok := degradedEndpointByID(endpoints, id); ok {
			return requireQueryableEndpoint(degraded)
		}
		return err
	}
	capabilities, capabilityErr := r.API.GetCapabilities(ctx, endpoint.EndpointID)
	detail := Detail{Endpoint: endpoint, Session: session, Inventory: report, Capabilities: capabilities}
	resourceID := ""
	if session != nil {
		resourceID = session.ClusterSessionID
	}
	if commands, commandErr := r.API.ListCommands(ctx, endpoint.EndpointID, resourceID, 20); commandErr == nil {
		detail.CommandHistory = commands
	} else {
		detail.Unavailable = append(detail.Unavailable, "commands: "+commandErr.Error())
	}
	if capabilityErr != nil {
		detail.Unavailable = append(detail.Unavailable, "capabilities: "+capabilityErr.Error())
	}
	if jsonMode {
		return RenderJSON(out, detail)
	}
	RenderDetail(out, detail)
	return nil
}

// Logs retrieves and renders a bounded output snapshot. color decides whether
// provider SGR colour survives; every other escape sequence is always stripped.
func (r CommandRunner) Logs(ctx context.Context, out io.Writer, endpointID, resourceID string, maxBytes, maxLines int, jsonMode bool, color ColorPolicy) error {
	report, err := r.API.GetInventory(ctx, endpointID)
	if err != nil {
		return err
	}
	generation := ""
	for _, session := range report.Sessions {
		if session.ClusterSessionID == resourceID {
			generation = session.ProviderGeneration
			break
		}
	}
	if jsonMode {
		snapshot, err := r.API.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
		if err != nil {
			return err
		}
		return RenderJSON(out, snapshot)
	}
	return r.RenderSessionSnapshot(ctx, out, endpointID, resourceID, generation, maxBytes, maxLines, color)
}

// RenderSessionSnapshot reads and renders one bounded output snapshot for an
// already validated generation, so a caller that just validated the selection
// does not repeat the inventory round trip.
func (r CommandRunner) RenderSessionSnapshot(ctx context.Context, out io.Writer, endpointID, resourceID, generation string, maxBytes, maxLines int, color ColorPolicy) error {
	snapshot, err := r.API.GetOutput(ctx, endpointID, resourceID, generation, maxBytes, maxLines)
	if err != nil {
		return err
	}
	if snapshot.ErrorCode != "" {
		_, err = fmt.Fprintln(out, sanitizeTerminal([]byte(snapshot.ErrorCode)))
		return err
	}
	RenderSnapshotStyled(out, snapshot.ObservedAtMS, snapshot.Data, snapshot.Truncated, maxLines, color)
	return nil
}

// Status retrieves and renders one durable command result.
func (r CommandRunner) Status(ctx context.Context, out io.Writer, commandID string, jsonMode bool) error {
	result, err := r.API.GetCommand(ctx, commandID)
	if err != nil {
		return err
	}
	if jsonMode {
		return RenderJSON(out, result)
	}
	if r.Policy == InteractivePolicy {
		return renderInteractiveStartResult(out, commandID, result)
	}
	_, err = fmt.Fprintln(out, StatusLabel(protocol.CommandStatus(stringValue(result, "status")), ReceiptForStatus(result)))
	return err
}

func stringValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}
