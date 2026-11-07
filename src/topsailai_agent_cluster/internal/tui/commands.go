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
func (r CommandRunner) ListWithOptions(ctx context.Context, out, errors io.Writer, filter string, jsonMode bool, options TableOptions) error {
	loaded, err := loadReports(ctx, r.API, filter)
	if err != nil {
		return err
	}
	return renderListRows(out, errors, loaded, filter, jsonMode, options)
}

// renderListRows renders one already loaded inventory set, so a caller that
// validated the same load does not repeat the API round trip.
func renderListRows(out, errors io.Writer, loaded reportLoad, filter string, jsonMode bool, options TableOptions) error {
	rows := ListRows(loaded.endpoints, loaded.reports, filter)
	if jsonMode {
		return RenderJSON(out, rows)
	}
	if options.Clean && len(loaded.errors) > 0 {
		filtered := rows[:0]
		for _, row := range rows {
			if _, failed := loaded.errors[row.EndpointID]; !failed {
				filtered = append(filtered, row)
			}
		}
		rows = filtered
	}
	assignRowNumbers(rows)
	if options.OnRows != nil {
		options.OnRows(append([]SessionRow(nil), rows...))
	}
	failures := make([]EndpointFailure, 0, len(loaded.errors))
	for endpointID, fetchErr := range loaded.errors {
		failures = append(failures, EndpointFailure{EndpointID: endpointID, Err: fetchErr})
	}
	return RenderTable(out, errors, rows, failures, options)
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
		return err
	}
	capabilities, capabilityErr := r.API.GetCapabilities(ctx, endpoint.EndpointID)
	detail := Detail{Endpoint: endpoint, Session: session, Inventory: report, Capabilities: capabilities}
	resourceID := ""
	if session != nil {
		resourceID = session.SessionID
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
		if session.SessionID == resourceID {
			generation = session.Generation
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
