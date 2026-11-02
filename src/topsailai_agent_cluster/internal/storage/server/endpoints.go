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
