package adapters

import (
	"context"
	"errors"
	"io"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

type stubMetadataAdapter struct{}

func (s *stubMetadataAdapter) Init(ctx context.Context) error                       { return nil }
func (s *stubMetadataAdapter) Create(ctx context.Context, obj *models.Object) error { return nil }
func (s *stubMetadataAdapter) Get(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	return nil, nil
}
func (s *stubMetadataAdapter) Update(ctx context.Context, obj *models.Object) error { return nil }
func (s *stubMetadataAdapter) Delete(ctx context.Context, id models.ObjectID) error { return nil }
func (s *stubMetadataAdapter) FinalizeDelete(ctx context.Context, id models.ObjectID) error {
	return nil
}
func (s *stubMetadataAdapter) Purge(ctx context.Context, id models.ObjectID) error { return nil }
func (s *stubMetadataAdapter) List(ctx context.Context, opts models.ListOptions) ([]*models.Object, error) {
	return nil, nil
}
func (s *stubMetadataAdapter) Search(ctx context.Context, terms []string, opts models.ListOptions) ([]*models.Object, error) {
	return nil, nil
}
func (s *stubMetadataAdapter) AddTag(ctx context.Context, id models.ObjectID, tag string) error    { return nil }
func (s *stubMetadataAdapter) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error { return nil }
func (s *stubMetadataAdapter) Recover(ctx context.Context) ([]*models.Object, error)               { return nil, nil }
func (s *stubMetadataAdapter) GC(ctx context.Context, retention time.Duration) ([]*models.Object, error) {
	return nil, nil
}
func (s *stubMetadataAdapter) Close() error { return nil }

type stubActualDataAdapter struct{}

func (s *stubActualDataAdapter) Init(ctx context.Context) error { return nil }
func (s *stubActualDataAdapter) WriteArchive(ctx context.Context, ref string, r io.Reader) (string, error) {
	return ref, nil
}
func (s *stubActualDataAdapter) ReadArchive(ctx context.Context, ref string) (io.ReadCloser, error) {
	return nil, nil
}
func (s *stubActualDataAdapter) WriteFile(ctx context.Context, ref string, filename string, r io.Reader) (string, error) {
	return ref, nil
}
func (s *stubActualDataAdapter) ReadFile(ctx context.Context, ref string, filename string) (io.ReadCloser, error) {
	return nil, nil
}
func (s *stubActualDataAdapter) Move(ctx context.Context, oldRef string, newRef string) (string, error) {
	return newRef, nil
}
func (s *stubActualDataAdapter) Delete(ctx context.Context, ref string) error          { return nil }
func (s *stubActualDataAdapter) Exists(ctx context.Context, ref string) (bool, error)   { return false, nil }
func (s *stubActualDataAdapter) Close() error                                           { return nil }

func TestRegisterMetadataAdapter(t *testing.T) {
	factory := func(ctx context.Context, cfg map[string]string) (MetadataAdapter, error) {
		return &stubMetadataAdapter{}, nil
	}

	RegisterMetadataAdapter("test-meta", factory)
	adapter, err := NewMetadataAdapter(context.Background(), "test-meta", nil)
	if err != nil {
		t.Fatalf("NewMetadataAdapter failed: %v", err)
	}
	if adapter == nil {
		t.Fatal("expected non-nil adapter")
	}
}

func TestNewMetadataAdapterUnknown(t *testing.T) {
	_, err := NewMetadataAdapter(context.Background(), "unknown-meta", nil)
	if err == nil {
		t.Fatal("expected error for unknown metadata adapter")
	}
	if !errors.Is(err, apperrors.ErrAdapterNotFound) {
		t.Fatalf("expected ErrAdapterNotFound, got %v", err)
	}
}

func TestRegisterActualDataAdapter(t *testing.T) {
	factory := func(ctx context.Context, cfg map[string]string) (ActualDataAdapter, error) {
		return &stubActualDataAdapter{}, nil
	}

	RegisterActualDataAdapter("test-actual", factory)
	adapter, err := NewActualDataAdapter(context.Background(), "test-actual", nil)
	if err != nil {
		t.Fatalf("NewActualDataAdapter failed: %v", err)
	}
	if adapter == nil {
		t.Fatal("expected non-nil adapter")
	}
}

func TestNewActualDataAdapterUnknown(t *testing.T) {
	_, err := NewActualDataAdapter(context.Background(), "unknown-actual", nil)
	if err == nil {
		t.Fatal("expected error for unknown actual-data adapter")
	}
	if !errors.Is(err, apperrors.ErrAdapterNotFound) {
		t.Fatalf("expected ErrAdapterNotFound, got %v", err)
	}
}

func TestFactoryReceivesConfig(t *testing.T) {
	var received map[string]string
	factory := func(ctx context.Context, cfg map[string]string) (MetadataAdapter, error) {
		received = cfg
		return &stubMetadataAdapter{}, nil
	}

	RegisterMetadataAdapter("config-meta", factory)
	want := map[string]string{"key": "value"}
	if _, err := NewMetadataAdapter(context.Background(), "config-meta", want); err != nil {
		t.Fatalf("NewMetadataAdapter failed: %v", err)
	}
	if received["key"] != "value" {
		t.Fatalf("expected config key=value, got %v", received)
	}
}
