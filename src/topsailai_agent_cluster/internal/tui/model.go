// Package tui provides the provider-neutral operator terminal client.
package tui

import (
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// SessionRow is the stable list representation rendered by the TUI.
type SessionRow struct {
	No                       int    `json:"-"`
	EndpointID               string `json:"endpoint_id"`
	AdapterID                string `json:"adapter_id"`
	EndpointLabel            string `json:"-"`
	AdapterLabel             string `json:"-"`
	ClusterSessionID         string `json:"cluster_session_id"`
	ProviderSessionID        string `json:"provider_session_id,omitempty"`
	ProviderDisplayName      string `json:"provider_display_name,omitempty"`
	ProviderProjectWorkspace string `json:"provider_project_workspace,omitempty"`
	ProviderGeneration       string `json:"provider_generation"`
	State                    string `json:"state"`
	Stale                    bool   `json:"stale"`
	Unknown                  bool   `json:"unknown"`
	// Unverified marks a session the provider listed but whose liveness it could
	// not verify, so no generation was reported. Such a session is reported as
	// unknown rather than dropped, and only resume may address it. The flag is
	// derived from state_reason so the row, the info detail and the refusal
	// message can name the subset; the status summary line deliberately does not,
	// because it reports the reported state only.
	Unverified       bool   `json:"unverified,omitempty"`
	LastSuccessAtMS  *int64 `json:"last_success_at_ms,omitempty"`
	CollectionStatus string `json:"collection_status"`
	// Drive is the bounded controller summary reported by the provider. A nil
	// value means the provider reported no driver observation, which is not a
	// confirmed absence of a controller.
	Drive *protocol.DriveSummary `json:"drive,omitempty"`
}

// ListRows converts endpoint reports into a deterministic session list.
func ListRows(endpoints []protocol.Endpoint, reports map[string]protocol.InventoryReport, filter string) []SessionRow {
	rows := make([]SessionRow, 0)
	for _, endpoint := range endpoints {
		if filter != "" && endpoint.EndpointID != filter {
			continue
		}
		// Retained inventory from a disconnected Endpoint is historical, not current.
		endpointStale := endpoint.ConnectionState != "" && endpoint.ConnectionState != "online"
		report, ok := reports[endpoint.EndpointID]
		if !ok {
			rows = append(rows, SessionRow{EndpointID: endpoint.EndpointID, EndpointLabel: endpointLabel(endpoint), State: "no sessions", Stale: endpointStale, CollectionStatus: "unknown"})
			continue
		}
		freshness := make(map[string]protocol.AdapterSummary, len(report.Adapters))
		for _, adapter := range report.Adapters {
			freshness[adapter.AdapterID] = adapter
		}
		if len(report.Sessions) == 0 {
			lastSuccess := endpointLastSuccess(report)
			rows = append(rows, SessionRow{EndpointID: endpoint.EndpointID, EndpointLabel: endpointLabel(endpoint), State: "no sessions", Stale: endpointStale, CollectionStatus: report.CollectionStatus, LastSuccessAtMS: lastSuccess})
		}
		for _, session := range report.Sessions {
			adapter := freshness[session.AdapterID]
			rows = append(rows, SessionRow{
				EndpointID:               endpoint.EndpointID,
				EndpointLabel:            endpointLabel(endpoint),
				AdapterID:                session.AdapterID,
				AdapterLabel:             adapterLabel(adapter),
				ClusterSessionID:         session.ClusterSessionID,
				ProviderSessionID:        session.ProviderSessionID,
				ProviderDisplayName:      session.ProviderDisplayName,
				ProviderProjectWorkspace: session.ProviderProjectWorkspace,
				ProviderGeneration:       session.ProviderGeneration,
				State:                    session.State,
				Stale:                    adapter.Stale || endpointStale,
				Unknown:                  !adapter.DataKnown,
				Unverified:               session.StateReason == protocol.StateReasonLivenessUnverified,
				LastSuccessAtMS:          adapter.LastSuccessAtMS,
				CollectionStatus:         adapter.CollectionStatus,
				Drive:                    session.Drive,
			})
		}
	}
	return rows
}

// Detail is the stable show representation for one endpoint or session.
type Detail struct {
	Endpoint       protocol.Endpoint             `json:"endpoint"`
	Session        *protocol.Session             `json:"session,omitempty"`
	Inventory      protocol.InventoryReport      `json:"inventory"`
	Capabilities   protocol.CapabilityDescriptor `json:"capabilities"`
	CommandHistory []map[string]any              `json:"command_history"`
	Unavailable    []string                      `json:"unavailable,omitempty"`
}

// FindSession locates a session by ID and returns its endpoint report.
// The cluster resource ID is matched first across every endpoint, then the
// provider session ID, so the identifier an operator reads in the list is
// usable as input without changing the precedence of the existing form.
func FindSession(id string, endpoints []protocol.Endpoint, reports map[string]protocol.InventoryReport) (protocol.Endpoint, protocol.InventoryReport, *protocol.Session, error) {
	for _, endpoint := range endpoints {
		report, ok := reports[endpoint.EndpointID]
		if !ok {
			continue
		}
		if endpoint.EndpointID == id {
			return endpoint, report, nil, nil
		}
		for index := range report.Sessions {
			if report.Sessions[index].ClusterSessionID == id {
				return endpoint, report, &report.Sessions[index], nil
			}
		}
	}
	for _, endpoint := range endpoints {
		report, ok := reports[endpoint.EndpointID]
		if !ok {
			continue
		}
		for index := range report.Sessions {
			if report.Sessions[index].ProviderSessionID != "" && report.Sessions[index].ProviderSessionID == id {
				return endpoint, report, &report.Sessions[index], nil
			}
		}
	}
	return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("endpoint or session %q was not found", id)
}

// StatusLabel maps durable evidence to conservative operator wording.
func StatusLabel(status protocol.CommandStatus, receipt protocol.ExecutionReceipt) string {
	if status == protocol.StatusUnconfirmed {
		return "delivery unconfirmed, effect unknown"
	}
	if receipt.DeliveryBoundary == protocol.DeliverySignalSent && !receipt.ExitConfirmed {
		return "stop request sent"
	}
	switch status {
	case protocol.StatusAdmitted:
		return "server received"
	case protocol.StatusDispatched:
		return "request delivered"
	case protocol.StatusEndpointAdmitted:
		return "endpoint received"
	case protocol.StatusExecuting:
		if receipt.EffectCertainty == protocol.EffectUnknown {
			return "effect unknown"
		}
		return "executing"
	case protocol.StatusFinished:
		return "confirmed result"
	case protocol.StatusRejected, protocol.StatusFailed:
		return "failed"
	default:
		return string(status)
	}
}

func endpointLastSuccess(report protocol.InventoryReport) *int64 {
	var latest *int64
	for _, adapter := range report.Adapters {
		if adapter.LastSuccessAtMS != nil && (latest == nil || *adapter.LastSuccessAtMS > *latest) {
			v := *adapter.LastSuccessAtMS
			latest = &v
		}
	}
	return latest
}

func endpointLabel(endpoint protocol.Endpoint) string {
	if endpoint.Hostname != "" {
		return endpoint.Hostname
	}
	if endpoint.DisplayName != "" {
		return endpoint.DisplayName
	}
	return endpoint.EndpointID
}

func adapterLabel(adapter protocol.AdapterSummary) string {
	if adapter.ProviderType != "" {
		return adapter.ProviderType
	}
	return adapter.AdapterID
}
