package tui

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// RenderJSON writes stable indented JSON for scripting and BDD clients.
func RenderJSON(w io.Writer, value any) error {
	encoder := json.NewEncoder(w)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

// RenderRows writes a compact human-readable session list.
func RenderRows(w io.Writer, rows []SessionRow) {
	for _, row := range rows {
		markers := make([]string, 0, 2)
		if row.Stale {
			markers = append(markers, "stale")
		}
		if row.Unknown {
			markers = append(markers, "unknown")
		}
		lastSuccess := "never"
		if row.LastSuccessAtMS != nil {
			lastSuccess = fmt.Sprint(*row.LastSuccessAtMS)
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\tcollection_status=%s\tlast_success_at_ms=%s\t%s\n", row.EndpointID, row.AdapterID, row.SessionID, row.Generation, row.State, row.CollectionStatus, lastSuccess, strings.Join(markers, ","))
	}
}

// RenderDetail writes endpoint, session, capabilities, and command evidence.
func RenderDetail(w io.Writer, detail Detail) {
	fmt.Fprintf(w, "endpoint: %s (%s)\n", detail.Endpoint.EndpointID, detail.Endpoint.ConnectionState)
	lastSuccess := "never"
	for _, adapter := range detail.Inventory.Adapters {
		if adapter.LastSuccessAtMS != nil {
			lastSuccess = fmt.Sprint(*adapter.LastSuccessAtMS)
			break
		}
	}
	fmt.Fprintf(w, "collection_status: %s\nlast_success_at_ms: %s\n", detail.Inventory.CollectionStatus, lastSuccess)
	if detail.Session != nil {
		fmt.Fprintf(w, "session: %s adapter=%s generation=%s state=%s\n", detail.Session.SessionID, detail.Session.AdapterID, detail.Session.Generation, detail.Session.State)
	}
	fmt.Fprintf(w, "capabilities: %d\n", len(detail.Capabilities.Capabilities))
	for _, capability := range detail.Capabilities.Capabilities {
		fmt.Fprintf(w, "  %s/%s\n", capability.Name, capability.Version)
	}
	if len(detail.CommandHistory) == 0 {
		fmt.Fprintln(w, "no commands")
		return
	}
	fmt.Fprintf(w, "command history: %d\n", len(detail.CommandHistory))
	for _, command := range detail.CommandHistory {
		fmt.Fprintf(w, "  %s %s %s %s\n", shortCommandID(command), valueString(command, "operation"), valueString(command, "status"), valueString(command, "delivery_boundary"))
	}
}

// RenderSnapshot writes an explicit one-shot output snapshot result.
// maxLines bounds the content to its newest lines so a chatty session cannot
// flood the terminal; a non-positive limit keeps every line. The body is
// sanitized with colour disabled, so this entry point never emits an escape
// sequence; callers that own a colour policy use RenderSnapshotStyled.
func RenderSnapshot(w io.Writer, observedAtMS int64, content string, truncated bool, maxLines int) {
	RenderSnapshotStyled(w, observedAtMS, content, truncated, maxLines, ColorPolicy{})
}

// RenderSnapshotStyled writes a snapshot whose body keeps SGR colour when the
// policy is enabled. Every other escape sequence is still stripped, because the
// body is provider data and must never be able to move the cursor, retitle the
// window or open a hyperlink.
func RenderSnapshotStyled(w io.Writer, observedAtMS int64, content string, truncated bool, maxLines int, policy ColorPolicy) {
	bounded, clipped := TrimTailLines(content, maxLines)
	fmt.Fprintf(w, "observed_at_ms: %d\ntruncated: %t\n%s\n", observedAtMS, truncated || clipped, filterProviderOutput(bounded, policy))
}

// ReceiptForStatus builds a receipt value from a generic command response.
func ReceiptForStatus(value map[string]any) protocol.ExecutionReceipt {
	data, _ := json.Marshal(value)
	var receipt protocol.ExecutionReceipt
	_ = json.Unmarshal(data, &receipt)
	return receipt
}

func shortCommandID(command map[string]any) string {
	id := valueString(command, "command_id", "CommandID")
	if len(id) > 12 {
		return id[:12]
	}
	return id
}
func valueString(command map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := command[key].(string); ok {
			return value
		}
	}
	return ""
}

// TrimTailLines keeps at most maxLines trailing lines of a snapshot body.
// A non-positive bound disables the limit, so callers can opt out explicitly.
func TrimTailLines(content string, maxLines int) (string, bool) {
	if maxLines <= 0 {
		return content, false
	}
	trimmed := strings.TrimSuffix(content, "\n")
	if trimmed == "" {
		return content, false
	}
	lines := strings.Split(trimmed, "\n")
	if len(lines) <= maxLines {
		return content, false
	}
	return strings.Join(lines[len(lines)-maxLines:], "\n") + "\n", true
}
