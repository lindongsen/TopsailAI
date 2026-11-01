package serverstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// QueryOptions controls bounded endpoint listing.
type QueryOptions struct {
	Offset  int
	Limit   int
	SortKey string
	OrderBy string
}

// ListEndpoints returns a bounded, deterministic endpoint projection.
func (s *Store) ListEndpoints(ctx context.Context, options QueryOptions) ([]protocol.Endpoint, error) {
	if options.Limit <= 0 || options.Limit > 1000 {
		options.Limit = 1000
	}
	order := "ASC"
	if options.OrderBy == "desc" {
		order = "DESC"
	}
	sort := "endpoint_id"
	if options.SortKey == "update_at_ms" {
		sort = "update_at_ms"
	}
	query := fmt.Sprintf("SELECT endpoint_id, instance_id, display_name, connection_state, observed_at_ms, capability_revision FROM endpoints ORDER BY %s %s, endpoint_id ASC LIMIT ? OFFSET ?", sort, order)
	rows, err := s.db.QueryContext(ctx, query, options.Limit, options.Offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []protocol.Endpoint
	for rows.Next() {
		var item protocol.Endpoint
		if err := rows.Scan(&item.EndpointID, &item.InstanceID, &item.DisplayName, &item.ConnectionState, &item.ObservedAtMS, &item.CapabilityRevision); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

// GetInventory returns the latest complete report for an endpoint.
func (s *Store) GetInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	var report protocol.InventoryReport
	var payload string
	err := s.db.QueryRowContext(ctx, `SELECT sessions_json FROM endpoint_session_state WHERE endpoint_id = ?`, endpointID).Scan(&payload)
	if err == sql.ErrNoRows {
		return report, fmt.Errorf("endpoint %q inventory not found", endpointID)
	}
	if err != nil {
		return report, err
	}
	if err := jsonUnmarshal([]byte(payload), &report); err != nil {
		return report, err
	}
	return report, nil
}

var jsonUnmarshal = func(data []byte, target any) error { return json.Unmarshal(data, target) }
