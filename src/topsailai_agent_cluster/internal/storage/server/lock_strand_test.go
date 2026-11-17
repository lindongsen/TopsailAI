package serverstorage

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestConcurrentProductionWorkloadNeverStrandsTheWriteLock reproduces the
// Server's real write pattern and asserts the database never becomes
// permanently unwritable.
//
// The production outage had a specific shape that no existing test reproduced:
// callers received SQLITE_BUSY for almost three hours while the pool was
// configured with SetMaxOpenConns(1). That combination is only possible if the
// write lock is held by something the pool does not consider in use, because a
// caller waiting for the single pooled connection blocks instead of receiving
// SQLITE_BUSY.
//
// The workload below mirrors what the Server actually does concurrently:
//   - UpsertEndpoint on every inventory frame, which is a direct ExecContext and
//     therefore does not use withTransaction
//   - ReplaceInventoryCommitted on the same frame, which does use withTransaction
//   - the retention sweep, which mixes direct ExecContext statements with
//     withTransaction operations
//
// If any of those paths can strand the lock, this test fails with the operation
// that could not write, which is the evidence needed to fix it.
func TestConcurrentProductionWorkloadNeverStrandsTheWriteLock(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	// A short busy timeout keeps the test fast. It does not change the property
	// under test: a stranded lock never clears, so any timeout expires.
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=50`); err != nil {
		t.Fatal(err)
	}

	endpoints := []string{"ac.ai-dev", "ac.topsail", "ac.topsailai-dev"}
	deadline := time.Now().Add(3 * time.Second)

	var wg sync.WaitGroup
	errCh := make(chan error, 64)

	// Inventory frames: UpsertEndpoint then ReplaceInventoryCommitted, exactly as
	// the Server's inventory handler does.
	for _, endpointID := range endpoints {
		endpointID := endpointID
		wg.Add(1)
		go func() {
			defer wg.Done()
			revision := int64(1)
			for time.Now().Before(deadline) {
				now := time.Now().UnixMilli()
				if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
					EndpointID:         endpointID,
					InstanceID:         endpointID + "-1",
					DisplayName:        endpointID,
					Hostname:           endpointID,
					ConnectionState:    "online",
					ObservedAtMS:       now,
					CapabilityRevision: "topsailai-v1",
				}, now); err != nil {
					errCh <- fmt.Errorf("upsert endpoint %s: %w", endpointID, err)
					return
				}
				revision++
				report := protocol.InventoryReport{
					SchemaVersion:    "v1",
					SourceGeneration: "endpoint-local",
					SnapshotRevision: revision,
					ObservedAtMS:     now,
					ReportComplete:   true,
					CollectionStatus: protocol.CollectionSucceeded,
				}
				if err := store.ReplaceInventory(ctx, endpointID, report, now); err != nil {
					errCh <- fmt.Errorf("replace inventory %s: %w", endpointID, err)
					return
				}
			}
		}()
	}

	// Retention sweep: direct ExecContext statements followed by withTransaction
	// operations, in the same order expireEndpointRecords uses.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for time.Now().Before(deadline) {
			now := time.Now().UnixMilli()
			if _, err := store.ReconcileExpiredCommands(ctx, now); err != nil {
				errCh <- fmt.Errorf("reconcile expired commands: %w", err)
				return
			}
			if _, err := store.PurgeExpiredCommands(ctx, now); err != nil {
				errCh <- fmt.Errorf("purge expired commands: %w", err)
				return
			}
			if _, err := store.DegradeOfflineEndpoints(ctx, now, now, 5000); err != nil {
				errCh <- fmt.Errorf("degrade offline endpoints: %w", err)
				return
			}
			if _, err := store.ExpireDegradedEndpoints(ctx, now); err != nil {
				errCh <- fmt.Errorf("expire degraded endpoints: %w", err)
				return
			}
		}
	}()

	// Readers, so a writer must contend with SHARED locks under
	// journal_mode=DELETE.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for time.Now().Before(deadline) {
			if _, err := store.ListEndpoints(ctx, QueryOptions{Limit: 100}); err != nil {
				errCh <- fmt.Errorf("list endpoints: %w", err)
				return
			}
			if _, err := store.ListInventoryRevisions(ctx); err != nil {
				errCh <- fmt.Errorf("list inventory revisions: %w", err)
				return
			}
		}
	}()

	wg.Wait()
	close(errCh)

	var lockErrors []string
	for err := range errCh {
		lower := strings.ToLower(err.Error())
		if strings.Contains(lower, "locked") || strings.Contains(lower, "busy") {
			lockErrors = append(lockErrors, err.Error())
		}
	}

	// A transient SQLITE_BUSY is expected under contention with a 50ms timeout.
	// The failure this test exists for is a lock that never clears, so the
	// decisive check is whether the database is writable after the workload ends.
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = display_name`); err != nil {
		t.Fatalf("the database is not writable after the production workload, so the write lock was stranded; %d lock errors were observed during the run, first: %v", len(lockErrors), err)
	}
	if len(lockErrors) > 0 {
		t.Logf("observed %d transient lock errors under contention, first: %s", len(lockErrors), lockErrors[0])
	}
}
