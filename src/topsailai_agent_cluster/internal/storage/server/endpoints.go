package serverstorage

import (
	"context"
	"fmt"

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
