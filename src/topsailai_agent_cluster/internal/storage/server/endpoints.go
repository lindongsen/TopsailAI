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
	offlineSinceMS := int64(0)
	if endpoint.ConnectionState != "online" {
		offlineSinceMS = nowMS
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO endpoints(endpoint_id, instance_id, display_name, hostname, connection_state, offline_since_at_ms, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint_id) DO UPDATE SET instance_id=excluded.instance_id, display_name=excluded.display_name, hostname=excluded.hostname, connection_state=excluded.connection_state, offline_since_at_ms=CASE WHEN excluded.connection_state = 'online' THEN 0 WHEN endpoints.offline_since_at_ms > 0 THEN endpoints.offline_since_at_ms ELSE excluded.offline_since_at_ms END, observed_at_ms=excluded.observed_at_ms, capability_revision=excluded.capability_revision, update_at_ms=excluded.update_at_ms`, endpoint.EndpointID, endpoint.InstanceID, endpoint.DisplayName, endpoint.Hostname, endpoint.ConnectionState, offlineSinceMS, endpoint.ObservedAtMS, endpoint.CapabilityRevision, nowMS, nowMS)
	return err
}

// MarkEndpointOffline records a disconnect only while the stored instance still
// matches and no newer observation has already been persisted.
func (s *Store) MarkEndpointOffline(ctx context.Context, endpointID, instanceID string, observedAtMS int64) (bool, error) {
	if endpointID == "" || instanceID == "" {
		return false, fmt.Errorf("endpoint identity is required")
	}
	result, err := s.db.ExecContext(ctx, `UPDATE endpoints SET connection_state = 'offline', offline_since_at_ms = CASE WHEN offline_since_at_ms = 0 THEN ? ELSE offline_since_at_ms END, observed_at_ms = ?, update_at_ms = ? WHERE endpoint_id = ? AND instance_id = ? AND observed_at_ms <= ?`, observedAtMS, observedAtMS, observedAtMS, endpointID, instanceID, observedAtMS)
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
func (s *Store) MarkPersistedEndpointsOffline(ctx context.Context, offlineSinceMS int64) (int64, error) {
	if offlineSinceMS <= 0 {
		return 0, fmt.Errorf("endpoint offline timestamp must be positive")
	}
	result, err := s.db.ExecContext(ctx, `UPDATE endpoints SET connection_state = 'offline', offline_since_at_ms = ? WHERE connection_state = 'online'`, offlineSinceMS)
	if err != nil {
		return 0, fmt.Errorf("mark persisted endpoints offline: %w", err)
	}
	updated, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("count persisted endpoints marked offline: %w", err)
	}
	return updated, nil
}

// BackfillOfflineSince repairs rows that are offline but carry no retention
// clock. Such a row is unreachable: the expiry predicate requires
// offline_since_at_ms > 0, so no cutoff can ever select it. The state was
// created by a schema change that added the column with a zero default and did
// not backfill existing rows, and no later write path repairs it because these
// Endpoints never reconnect.
//
// update_at_ms is the correct source here even though it must never be the
// expiry predicate. The predicate needs a clock that unrelated metadata writes
// cannot refresh; a one-time backfill asks a different question, namely what the
// best available evidence of the offline moment is. For a row that has not been
// written since it went offline, that moment is its last write. After the
// backfill the value is frozen, so the predicate still reads only
// offline_since_at_ms.
//
// The update_at_ms > 0 guard makes the repair fail closed. A corrupt zero
// timestamp would otherwise copy zero into offline_since_at_ms and recreate the
// unreachable state, which is the defect this function exists to remove.
func (s *Store) BackfillOfflineSince(ctx context.Context) (int64, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE endpoints SET offline_since_at_ms = update_at_ms WHERE connection_state != 'online' AND offline_since_at_ms = 0 AND update_at_ms > 0`)
	if err != nil {
		return 0, fmt.Errorf("backfill endpoint offline timestamp: %w", err)
	}
	updated, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("count backfilled endpoint offline timestamps: %w", err)
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
	var inventoryIDs []string
	var endpointIDs []string
	err := s.withTransaction(ctx, "endpoint expiry", func(conn *sql.Conn) error {
		var err error
		inventoryIDs, err = deleteReturningEndpointIDs(ctx, conn, `DELETE FROM endpoint_session_state WHERE endpoint_id IN (SELECT endpoint_id FROM endpoints WHERE connection_state != 'online' AND offline_since_at_ms > 0 AND offline_since_at_ms <= ?) RETURNING endpoint_id`, cutoffMS)
		if err != nil {
			return fmt.Errorf("delete expired endpoint inventory: %w", err)
		}
		endpointIDs, err = deleteReturningEndpointIDs(ctx, conn, `DELETE FROM endpoints WHERE connection_state != 'online' AND offline_since_at_ms > 0 AND offline_since_at_ms <= ? AND NOT EXISTS (SELECT 1 FROM commands WHERE commands.endpoint_id = endpoints.endpoint_id) RETURNING endpoint_id`, cutoffMS)
		if err != nil {
			return fmt.Errorf("delete expired endpoint metadata: %w", err)
		}
		return nil
	})
	if err != nil {
		return EndpointExpiryResult{}, err
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
