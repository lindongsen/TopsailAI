package endpointstorage

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/adapter"
)

// ResourceMapping is the durable adapter-package mapping contract.
type ResourceMapping = adapter.ResourceMapping

// GetOrCreateResourceID returns a stable opaque ID without exposing provider paths.
func (s *Store) GetOrCreateResourceID(ctx context.Context, adapterID, providerKey string, nowMS int64) (ResourceMapping, error) {
	if adapterID == "" || providerKey == "" || nowMS < 1 {
		return ResourceMapping{}, errors.New("adapter ID, provider key and timestamp are required")
	}
	var mapping ResourceMapping
	err := s.db.QueryRowContext(ctx, `SELECT adapter_id, provider_key, resource_id FROM resource_mapping WHERE adapter_id=? AND provider_key=?`, adapterID, providerKey).Scan(&mapping.AdapterID, &mapping.ProviderKey, &mapping.ResourceID)
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
	_, err = s.db.ExecContext(ctx, `INSERT INTO resource_mapping(adapter_id, provider_key, resource_id, created_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?)`, adapterID, providerKey, resourceID, nowMS, nowMS)
	if err != nil {
		var existing ResourceMapping
		if retryErr := s.db.QueryRowContext(ctx, `SELECT adapter_id, provider_key, resource_id FROM resource_mapping WHERE adapter_id=? AND provider_key=?`, adapterID, providerKey).Scan(&existing.AdapterID, &existing.ProviderKey, &existing.ResourceID); retryErr == nil {
			return existing, nil
		}
		return ResourceMapping{}, fmt.Errorf("store resource mapping: %w", err)
	}
	return ResourceMapping{AdapterID: adapterID, ProviderKey: providerKey, ResourceID: resourceID}, nil
}

func randomResourceID() (string, error) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", fmt.Errorf("generate resource ID: %w", err)
	}
	return "res_" + hex.EncodeToString(raw[:]), nil
}

// LookupResourceID returns the durable source mapping for an opaque resource ID.
func (s *Store) LookupResourceID(ctx context.Context, resourceID string) (ResourceMapping, error) {
	if resourceID == "" {
		return ResourceMapping{}, errors.New("resource ID is required")
	}
	var mapping ResourceMapping
	err := s.db.QueryRowContext(ctx, `SELECT adapter_id, provider_key, resource_id FROM resource_mapping WHERE resource_id=?`, resourceID).Scan(&mapping.AdapterID, &mapping.ProviderKey, &mapping.ResourceID)
	if errors.Is(err, sql.ErrNoRows) {
		return ResourceMapping{}, fmt.Errorf("resource mapping for %q not found", resourceID)
	}
	if err != nil {
		return ResourceMapping{}, fmt.Errorf("lookup resource mapping: %w", err)
	}
	return mapping, nil
}
