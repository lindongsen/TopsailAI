package errors

import (
	"errors"
	"fmt"
	"testing"
)

func TestSentinelErrors(t *testing.T) {
	cases := []struct {
		name string
		err  error
	}{
		{"ErrObjectNotFound", ErrObjectNotFound},
		{"ErrObjectExists", ErrObjectExists},
		{"ErrObjectLocked", ErrObjectLocked},
		{"ErrObjectNotActive", ErrObjectNotActive},
		{"ErrObjectCeased", ErrObjectCeased},
		{"ErrObjectCreating", ErrObjectCreating},
		{"ErrInvalidName", ErrInvalidName},
		{"ErrInvalidPath", ErrInvalidPath},
		{"ErrInvalidStatus", ErrInvalidStatus},
		{"ErrInvalidTag", ErrInvalidTag},
		{"ErrInvalidDepth", ErrInvalidDepth},
		{"ErrDepthExceeded", ErrDepthExceeded},
		{"ErrInvalidArgument", ErrInvalidArgument},
		{"ErrInvalidSearchQuery", ErrInvalidSearchQuery},
		{"ErrAdapterNotFound", ErrAdapterNotFound},
		{"ErrMoveNotSupported", ErrMoveNotSupported},
		{"ErrAdapterConfig", ErrAdapterConfig},
		{"ErrNotImplemented", ErrNotImplemented},
		{"ErrCancelled", ErrCancelled},
		{"ErrTimeout", ErrTimeout},
		{"ErrCorruptedMetadata", ErrCorruptedMetadata},
		{"ErrTagNotFound", ErrTagNotFound},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if tc.err == nil {
				t.Fatal("expected non-nil sentinel error")
			}
			if tc.err.Error() == "" {
				t.Fatal("expected non-empty error message")
			}
		})
	}
}

func TestSentinelsAreDistinct(t *testing.T) {
	sentinels := []error{
		ErrObjectNotFound,
		ErrObjectExists,
		ErrObjectLocked,
		ErrObjectNotActive,
		ErrObjectCeased,
		ErrObjectCreating,
		ErrInvalidName,
		ErrInvalidPath,
		ErrInvalidStatus,
		ErrInvalidTag,
		ErrInvalidDepth,
		ErrDepthExceeded,
		ErrInvalidArgument,
		ErrInvalidSearchQuery,
		ErrAdapterNotFound,
		ErrMoveNotSupported,
		ErrAdapterConfig,
		ErrNotImplemented,
		ErrCancelled,
		ErrTimeout,
		ErrCorruptedMetadata,
		ErrTagNotFound,
	}

	for i := 0; i < len(sentinels); i++ {
		for j := i + 1; j < len(sentinels); j++ {
			if errors.Is(sentinels[i], sentinels[j]) {
				t.Fatalf("sentinels %d and %d match with errors.Is", i, j)
			}
		}
	}
}

func TestErrorWrapping(t *testing.T) {
	wrapped := fmt.Errorf("get object: %w", ErrObjectNotFound)
	if !errors.Is(wrapped, ErrObjectNotFound) {
		t.Fatal("expected errors.Is to match wrapped ErrObjectNotFound")
	}
}
