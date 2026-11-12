package serverstorage

import (
	"context"
	"database/sql"
	"fmt"
	"sort"

	"topsailai_agent_cluster/internal/protocol"
)

// UpsertEndpoint stores the latest endpoint metadata transactionally.
func (s *Store) UpsertEndpoint(ctx context.Context, endpoint protocol.Endpoint, nowMS int64) error {
	if endpoint.EndpointID == "" || endpoint.InstanceID == "" {
		return fmt.Errorf("endpoint identity is required")
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO endpoints(endpoint_id, instance_id, display_name, hostname, connection_state, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint_id) DO UPDATE SET instance_id=excluded.instance_id, display_name=excluded.display_name, hostname=excluded.hostname, connection_state=excluded.connection_state, observed_at_ms=excluded.observed_at_ms, capability_revision=excluded.capability_revision, update_at_ms=excluded.update_at_ms`, endpoint.EndpointID, endpoint.InstanceID, endpoint.DisplayName, endpoint.Hostname, endpoint.ConnectionState, endpoint.ObservedAtMS, endpoint.CapabilityRevision, nowMS, nowMS)
	return err
}

// MarkEndpointOffline records a disconnect only while the stored instance still
// matches and no newer observation has already been persisted.
func (s *Store) MarkEndpointOffline(ctx context.Context, endpointID, instanceID string, observedAtMS int64) (bool, error) {
	if endpointID == "" || instanceID == "" {
		return false, fmt.Errorf("endpoint identity is required")
	}
	result, err := s.db.ExecContext(ctx, `UPDATE endpoints SET connection_state = 'offline', observed_at_ms = ?, update_at_ms = ? WHERE endpoint_id = ? AND instance_id = ? AND observed_at_ms <= ?`, observedAtMS, observedAtMS, endpointID, instanceID, observedAtMS)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	return affected > 0, nil
}

// MarkPersistedEndpointsOffline clears stale online projections during Server
// startup without refreshing their age. No channel survives a Server process
// restart, and a reconnect will publish a newer online observation normally.
func (s *Store) MarkPersistedEndpointsOffline(ctx context.Context) (int64, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE endpoints SET connection_state = 'offline' WHERE connection_state = 'online'`)
	if err != nil {
		return 0, fmt.Errorf("mark persisted endpoints offline: %w", err)
	}
	updated, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("count persisted endpoints marked offline: %w", err)
	}
	return updated, nil
}

// EndpointExpiryResult identifies every stale Server projection removed.
type EndpointExpiryResult struct {
	InventoryEndpointIDs []string
	DeletedEndpointIDs   []string
}

// ExpireOfflineEndpoints removes stale offline inventory while preserving every
// Endpoint row that retained command evidence still references. The state and
// cutoff predicates are repeated for each delete inside one transaction so a
// reconnect can never be removed by a stale selection made before the write.
func (s *Store) ExpireOfflineEndpoints(ctx context.Context, cutoffMS int64) (EndpointExpiryResult, error) {
	if cutoffMS <= 0 {
		return EndpointExpiryResult{}, fmt.Errorf("endpoint expiry cutoff must be positive")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return EndpointExpiryResult{}, fmt.Errorf("begin endpoint expiry: %w", err)
	}
	defer tx.Rollback()

	inventoryIDs, err := deleteReturningEndpointIDs(ctx, tx, `DELETE FROM endpoint_session_state WHERE endpoint_id IN (SELECT endpoint_id FROM endpoints WHERE connection_state != 'online' AND update_at_ms <= ?) RETURNING endpoint_id`, cutoffMS)
	if err != nil {
		return EndpointExpiryResult{}, fmt.Errorf("delete expired endpoint inventory: %w", err)
	}
	endpointIDs, err := deleteReturningEndpointIDs(ctx, tx, `DELETE FROM endpoints WHERE connection_state != 'online' AND update_at_ms <= ? AND NOT EXISTS (SELECT 1 FROM commands WHERE commands.endpoint_id = endpoints.endpoint_id) RETURNING endpoint_id`, cutoffMS)
	if err != nil {
		return EndpointExpiryResult{}, fmt.Errorf("delete expired endpoint metadata: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return EndpointExpiryResult{}, fmt.Errorf("commit endpoint expiry: %w", err)
	}
	sort.Strings(inventoryIDs)
	sort.Strings(endpointIDs)
	return EndpointExpiryResult{InventoryEndpointIDs: inventoryIDs, DeletedEndpointIDs: endpointIDs}, nil
}

// deleteReturningEndpointIDs executes one expiry delete and collects its exact
// identities so the caller can emit an audit log for every removed record.
func deleteReturningEndpointIDs(ctx context.Context, tx interface {
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}, query string, cutoffMS int64) ([]string, error) {
	rows, err := tx.QueryContext(ctx, query, cutoffMS)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var endpointIDs []string
	for rows.Next() {
		var endpointID string
		if err := rows.Scan(&endpointID); err != nil {
			return nil, err
		}
		endpointIDs = append(endpointIDs, endpointID)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return endpointIDs, nil
}
