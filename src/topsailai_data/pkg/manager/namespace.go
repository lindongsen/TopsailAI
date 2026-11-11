package manager

import (
	"log/slog"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
)

// releaseNamespaceLock records release failures instead of hiding them.
func releaseNamespaceLock(lock *local.Lock) {
	if err := lock.Release(); err != nil {
		slog.Error("release namespace lock", "path", lock.Path(), "error", err)
	}
}
