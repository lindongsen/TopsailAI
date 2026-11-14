package endpointstorage

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// ErrResourceNotFound reports that no durable mapping exists for a resource ID.
// It is a legitimate rejection cause, not an infrastructure failure, so callers
// can record a terminal command outcome instead of leaving the command pending.
var ErrResourceNotFound = errors.New("resource mapping not found")

// ResourceMapping is the durable adapter-package mapping contract.
type ResourceMapping = adapter.ResourceMapping

// GetOrCreateResourceID returns a stable opaque ID without exposing provider paths.
func (s *Store) GetOrCreateResourceID(ctx context.Context, adapterID, resourceKind, providerResourceKey string, nowMS int64) (ResourceMapping, error) {
	if adapterID == "" || providerResourceKey == "" || nowMS < 1 {
		return ResourceMapping{}, errors.New("adapter ID, provider resource key and timestamp are required")
	}
	if !protocol.IsResourceKind(resourceKind) {
		return ResourceMapping{}, fmt.Errorf("invalid resource kind %q", resourceKind)
	}
	var mapping ResourceMapping
	err := s.db.QueryRowContext(ctx, `SELECT adapter_id, resource_kind, provider_resource_key, resource_id FROM resource_mapping WHERE adapter_id=? AND resource_kind=? AND provider_resource_key=?`, adapterID, resourceKind, providerResourceKey).Scan(&mapping.AdapterID, &mapping.ResourceKind, &mapping.ProviderResourceKey, &mapping.ResourceID)
	if err == nil {
		return mapping, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return ResourceMapping{}, err
	}
	resourceID, err := randomResourceID()
	if err != nil {
		return ResourceMapping{}, err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO resource_mapping(adapter_id, resource_kind, provider_resource_key, resource_id, created_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?)`, adapterID, resourceKind, providerResourceKey, resourceID, nowMS, nowMS)
	if err != nil {
		var existing ResourceMapping
		retryErr := s.db.QueryRowContext(ctx, `SELECT adapter_id, resource_kind, provider_resource_key, resource_id FROM resource_mapping WHERE adapter_id=? AND resource_kind=? AND provider_resource_key=?`, adapterID, resourceKind, providerResourceKey).Scan(&existing.AdapterID, &existing.ResourceKind, &existing.ProviderResourceKey, &existing.ResourceID)
		if retryErr == nil {
			return existing, nil
		}
		return ResourceMapping{}, fmt.Errorf("store resource mapping: %w", err)
	}
	return ResourceMapping{AdapterID: adapterID, ResourceKind: resourceKind, ProviderResourceKey: providerResourceKey, ResourceID: resourceID}, nil
}

func randomResourceID() (string, error) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", fmt.Errorf("generate resource ID: %w", err)
	}
	return protocol.ClusterResourceIDPrefix + hex.EncodeToString(raw[:]), nil
}

// LookupResourceID returns the durable source mapping for an opaque resource ID.
func (s *Store) LookupResourceID(ctx context.Context, resourceID string) (ResourceMapping, error) {
	if resourceID == "" {
		return ResourceMapping{}, errors.New("resource ID is required")
	}
	var mapping ResourceMapping
	err := s.db.QueryRowContext(ctx, `SELECT adapter_id, resource_kind, provider_resource_key, resource_id FROM resource_mapping WHERE resource_id=?`, resourceID).Scan(&mapping.AdapterID, &mapping.ResourceKind, &mapping.ProviderResourceKey, &mapping.ResourceID)
	if errors.Is(err, sql.ErrNoRows) {
		return ResourceMapping{}, fmt.Errorf("%w: %q", ErrResourceNotFound, resourceID)
	}
	if err != nil {
		return ResourceMapping{}, fmt.Errorf("lookup resource mapping: %w", err)
	}
	return mapping, nil
}
