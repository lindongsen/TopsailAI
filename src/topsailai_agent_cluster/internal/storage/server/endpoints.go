package serverstorage

import (
	"context"
	"database/sql"
	"fmt"
	"sort"

	"topsailai_agent_cluster/internal/protocol"
)

// UpsertEndpoint stores the latest endpoint metadata transactionally.
//
// A reconnect clears the degraded clock and the deletion deadline, because a
// machine that is online again is not scheduled for deletion. Leaving either
// value behind would keep a stale deadline on a live row: the endpoint list
// would advertise a deletion date for an online machine, and a later sweep would
// delete a row that had already recovered. The clear is conditional on the
// incoming state being online, so a non-online report cannot erase the deadline
// of a row that is already degraded.
//
// A non-online report also preserves the degraded state. Degradation is decided
// by the sweep, not by the Endpoint, so an offline report from a degraded
// Endpoint must not silently restore it to offline: that would drop it out of
// the expiry predicate and the row would never be deleted. Only an online report
// leaves the degraded state.
func (s *Store) UpsertEndpoint(ctx context.Context, endpoint protocol.Endpoint, nowMS int64) error {
	if endpoint.EndpointID == "" || endpoint.InstanceID == "" {
		return fmt.Errorf("endpoint identity is required")
	}
	offlineSinceMS := int64(0)
	if endpoint.ConnectionState != "online" {
		offlineSinceMS = nowMS
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO endpoints(endpoint_id, instance_id, display_name, hostname, connection_state, offline_since_at_ms, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(endpoint_id) DO UPDATE SET instance_id=excluded.instance_id, display_name=excluded.display_name, hostname=excluded.hostname, connection_state=CASE WHEN endpoints.connection_state = 'degraded' AND excluded.connection_state != 'online' THEN 'degraded' ELSE excluded.connection_state END, offline_since_at_ms=CASE WHEN excluded.connection_state = 'online' THEN 0 WHEN endpoints.offline_since_at_ms > 0 THEN endpoints.offline_since_at_ms ELSE excluded.offline_since_at_ms END, degraded_since_at_ms=CASE WHEN excluded.connection_state = 'online' THEN 0 ELSE endpoints.degraded_since_at_ms END, expires_at_ms=CASE WHEN excluded.connection_state = 'online' THEN 0 ELSE endpoints.expires_at_ms END, observed_at_ms=excluded.observed_at_ms, capability_revision=excluded.capability_revision, update_at_ms=excluded.update_at_ms`, endpoint.EndpointID, endpoint.InstanceID, endpoint.DisplayName, endpoint.Hostname, endpoint.ConnectionState, offlineSinceMS, endpoint.ObservedAtMS, endpoint.CapabilityRevision, nowMS, nowMS)
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
	DeletedCommandIDs    []string
}

// EndpointDegradeResult identifies every Endpoint moved into the degraded state.
type EndpointDegradeResult struct {
	DegradedEndpointIDs  []string
	InventoryEndpointIDs []string
}

// DegradeOfflineEndpoints moves every Endpoint that has been offline past the
// offline retention window into the degraded state, and removes the inventory
// projection that made it look alive.
//
// Degrading is not deleting. The metadata row survives so an operator can still
// see that the machine existed, when it was last seen and when it will be
// removed, while the inventory is dropped because a stale session list is worse
// than no session list: it invites an operator to act on a machine that is gone.
//
// expires_at_ms is materialized here, once, rather than derived at query time.
// The query layer has no access to Server configuration, and a later retention
// change must not retroactively move the deletion date of a row that is already
// degraded. The promise made at degrade time stands, which is the same reason
// commands.deadline_at_ms is immutable.
//
// The inventory delete selects by the degraded_since_at_ms value written by the
// statement above, so it can only remove inventory belonging to rows degraded in
// this sweep. Selecting by the cutoff instead would also match a row that
// reconnected between the two statements.
func (s *Store) DegradeOfflineEndpoints(ctx context.Context, cutoffMS, nowMS, retentionMS int64) (EndpointDegradeResult, error) {
	if cutoffMS <= 0 {
		return EndpointDegradeResult{}, fmt.Errorf("endpoint degrade cutoff must be positive")
	}
	if nowMS <= 0 {
		return EndpointDegradeResult{}, fmt.Errorf("endpoint degrade timestamp must be positive")
	}
	if retentionMS <= 0 {
		return EndpointDegradeResult{}, fmt.Errorf("endpoint degraded retention must be positive")
	}
	var degradedIDs []string
	var inventoryIDs []string
	err := s.withTransaction(ctx, "endpoint degrade", func(conn *sql.Conn) error {
		var err error
		degradedIDs, err = queryReturningIDs(ctx, conn, `UPDATE endpoints SET connection_state = 'degraded', degraded_since_at_ms = ?, expires_at_ms = ?, update_at_ms = ? WHERE connection_state = 'offline' AND offline_since_at_ms > 0 AND offline_since_at_ms <= ? RETURNING endpoint_id`, nowMS, nowMS+retentionMS, nowMS, cutoffMS)
		if err != nil {
			return fmt.Errorf("degrade offline endpoints: %w", err)
		}
		inventoryIDs, err = queryReturningIDs(ctx, conn, `DELETE FROM endpoint_session_state WHERE endpoint_id IN (SELECT endpoint_id FROM endpoints WHERE connection_state = 'degraded' AND degraded_since_at_ms = ?) RETURNING endpoint_id`, nowMS)
		if err != nil {
			return fmt.Errorf("delete degraded endpoint inventory: %w", err)
		}
		return nil
	})
	if err != nil {
		return EndpointDegradeResult{}, err
	}
	sort.Strings(degradedIDs)
	sort.Strings(inventoryIDs)
	return EndpointDegradeResult{DegradedEndpointIDs: degradedIDs, InventoryEndpointIDs: inventoryIDs}, nil
}

// ExpireDegradedEndpoints deletes every Endpoint whose degraded deadline has
// passed, together with the command evidence that references it.
//
// The command delete is an explicit cascade rather than an ON DELETE CASCADE
// constraint. The schema declares commands.endpoint_id without a cascade, so a
// row with retained command evidence could never be deleted, and unconfirmed is
// deliberately excluded from the purge allowlist because it is the only evidence
// of an unknown effect. Deleting the endpoint therefore requires deleting those
// commands, and doing it explicitly is what lets every removed command ID be
// returned and logged. A schema cascade would remove the same rows silently.
//
// The state and deadline predicates are repeated for each delete inside one
// transaction so a reconnect can never be removed by a stale selection made
// before the write.
func (s *Store) ExpireDegradedEndpoints(ctx context.Context, cutoffMS int64) (EndpointExpiryResult, error) {
	if cutoffMS <= 0 {
		return EndpointExpiryResult{}, fmt.Errorf("endpoint expiry cutoff must be positive")
	}
	var commandIDs []string
	var inventoryIDs []string
	var endpointIDs []string
	err := s.withTransaction(ctx, "endpoint expiry", func(conn *sql.Conn) error {
		var err error
		commandIDs, err = queryReturningIDs(ctx, conn, `DELETE FROM commands WHERE endpoint_id IN (SELECT endpoint_id FROM endpoints WHERE connection_state = 'degraded' AND expires_at_ms > 0 AND expires_at_ms <= ?) RETURNING command_id`, cutoffMS)
		if err != nil {
			return fmt.Errorf("delete expired endpoint commands: %w", err)
		}
		inventoryIDs, err = queryReturningIDs(ctx, conn, `DELETE FROM endpoint_session_state WHERE endpoint_id IN (SELECT endpoint_id FROM endpoints WHERE connection_state = 'degraded' AND expires_at_ms > 0 AND expires_at_ms <= ?) RETURNING endpoint_id`, cutoffMS)
		if err != nil {
			return fmt.Errorf("delete expired endpoint inventory: %w", err)
		}
		endpointIDs, err = queryReturningIDs(ctx, conn, `DELETE FROM endpoints WHERE connection_state = 'degraded' AND expires_at_ms > 0 AND expires_at_ms <= ? RETURNING endpoint_id`, cutoffMS)
		if err != nil {
			return fmt.Errorf("delete expired endpoint metadata: %w", err)
		}
		return nil
	})
	if err != nil {
		return EndpointExpiryResult{}, err
	}
	sort.Strings(commandIDs)
	sort.Strings(inventoryIDs)
	sort.Strings(endpointIDs)
	return EndpointExpiryResult{InventoryEndpointIDs: inventoryIDs, DeletedEndpointIDs: endpointIDs, DeletedCommandIDs: commandIDs}, nil
}

// queryReturningIDs executes one statement that returns a single identity column
// and collects every value, so the caller can emit an audit log for each removed
// or transitioned record.
func queryReturningIDs(ctx context.Context, tx interface {
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}, query string, args ...any) ([]string, error) {
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return ids, nil
}
