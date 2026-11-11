package local

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// metadataRecord is the local disk contract; tags have a separate authority.
// Public Object serialization must remain independent of this representation.
type metadataRecord struct {
	ID            models.ObjectID
	Name          string
	Path          string
	Description   string
	Status        models.ObjectStatus
	SchemaVersion int
	CreatedAt     time.Time
	UpdatedAt     time.Time
	DeletedAt     *time.Time
	CeasedAt      *time.Time
	DataRef       string
}

// encodeMetadataRecord serializes disk fields without mutating the public model.
func encodeMetadataRecord(obj *models.Object) ([]byte, error) {
	if obj == nil {
		return nil, fmt.Errorf("nil metadata: %w", apperrors.ErrInvalidArgument)
	}
	if err := validateMetadataIdentity(obj); err != nil {
		return nil, err
	}
	record := metadataRecord{
		ID: obj.ID, Name: obj.Name, Path: obj.Path, Description: obj.Description,
		Status: obj.Status, SchemaVersion: obj.SchemaVersion, CreatedAt: obj.CreatedAt,
		UpdatedAt: obj.UpdatedAt, DeletedAt: obj.DeletedAt, CeasedAt: obj.CeasedAt, DataRef: obj.DataRef,
	}
	data, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("encode metadata record: %w", err)
	}
	return append(data, '\n'), nil
}

// decodeMetadataRecord refuses incompatible records rather than migrating them.
func decodeMetadataRecord(data []byte) (*models.Object, error) {
	var record metadataRecord
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&record); err != nil {
		return nil, fmt.Errorf("decode metadata record: %w: %v", apperrors.ErrCorruptedMetadata, err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return nil, fmt.Errorf("trailing metadata content: %w", apperrors.ErrCorruptedMetadata)
	}
	obj := &models.Object{
		ID: record.ID, Name: record.Name, Path: record.Path, Description: record.Description,
		Status: record.Status, SchemaVersion: record.SchemaVersion, CreatedAt: record.CreatedAt,
		UpdatedAt: record.UpdatedAt, DeletedAt: record.DeletedAt, CeasedAt: record.CeasedAt, DataRef: record.DataRef,
	}
	if err := validateMetadataIdentity(obj); err != nil {
		return nil, fmt.Errorf("invalid metadata identity: %w: %v", apperrors.ErrCorruptedMetadata, err)
	}
	return obj, nil
}

// validateMetadataIdentity enforces the local ID/name and schema contract.
// Local path syntax and identity are checked here; filesystem containment is checked on access.
func validateMetadataIdentity(obj *models.Object) error {
	if err := ValidateObjectName(string(obj.ID)); err != nil {
		return err
	}
	if obj.Name != string(obj.ID) {
		return fmt.Errorf("metadata name differs from ID: %w", apperrors.ErrInvalidName)
	}
	if obj.SchemaVersion != models.CurrentSchemaVersion {
		return fmt.Errorf("unsupported object schema %d: %w", obj.SchemaVersion, apperrors.ErrCorruptedMetadata)
	}
	switch obj.Status {
	case models.ObjectStatusCreating, models.ObjectStatusActive, models.ObjectStatusDeleted, models.ObjectStatusCeased:
	default:
		return fmt.Errorf("unknown object status %q: %w", obj.Status, apperrors.ErrCorruptedMetadata)
	}
	parts, err := validateObjectRef(obj.Path)
	if err != nil {
		return fmt.Errorf("invalid metadata path: %w", err)
	}
	if parts[len(parts)-1] != obj.Name || obj.DataRef != obj.Path {
		return fmt.Errorf("metadata path and reference differ from object identity: %w", apperrors.ErrCorruptedMetadata)
	}
	return nil
}
