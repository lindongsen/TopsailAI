package serverstorage

import "context"

// ListInventoryRevisions returns only current endpoint revisions for reconciliation.
func (s *Store) ListInventoryRevisions(ctx context.Context) ([]ManifestRevision, error) {
	queryCtx := ctx
	if queryCtx == nil {
		queryCtx = context.Background()
	}
	rows, err := s.db.QueryContext(queryCtx, `SELECT endpoint_id, snapshot_revision FROM endpoint_session_state ORDER BY endpoint_id ASC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]ManifestRevision, 0)
	for rows.Next() {
		var item ManifestRevision
		if err := rows.Scan(&item.EndpointID, &item.SnapshotRevision); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

// ManifestRevision is one durable current endpoint revision.
type ManifestRevision struct {
	EndpointID       string
	SnapshotRevision int64
}
