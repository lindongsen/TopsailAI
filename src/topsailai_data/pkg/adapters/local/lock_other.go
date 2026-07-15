//go:build !unix

package local

import (
	"os"

	"github.com/topsailai/topsailai_data/pkg/errors"
)

// flockAcquire returns ErrNotImplemented on non-Unix platforms because advisory
// file locking is not available in a portable way.
func flockAcquire(f *os.File, exclusive bool) error {
	_ = f
	_ = exclusive
	return errors.ErrNotImplemented
}

// flockRelease is a no-op on non-Unix platforms.
func flockRelease(f *os.File) error {
	return nil
}
