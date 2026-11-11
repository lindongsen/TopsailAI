package manager

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
)

// TestCutoverStatistics checks hash addressing, exact concurrent counts and lifecycle freeze.
func TestCutoverStatistics(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = true
	ctx := context.Background()
	obj := createTestObject(t, mgr, "stat-probe")
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	stat, err := local.ReadStat(dir)
	if err != nil || stat.WriteCount != 1 {
		t.Fatalf("creation statistics: %+v %v", stat, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "stat.json")); err != nil {
		t.Fatal(err)
	}
	payload, err := layout.ResolveObjectRef(obj.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(payload, "stat.json")); !os.IsNotExist(err) {
		t.Fatalf("payload contains statistic: %v", err)
	}
	const workers = 6
	const reads = 8
	var wg sync.WaitGroup
	failures := make(chan error, workers)
	for worker := 0; worker < workers; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for n := 0; n < reads; n++ {
				reader, err := mgr.ReadActualFile(ctx, obj.ID, obj.Name+".md")
				if err != nil {
					failures <- err
					return
				}
				_, copyErr := io.Copy(io.Discard, reader)
				closeErr := reader.Close()
				if copyErr != nil {
					failures <- copyErr
					return
				}
				if closeErr != nil {
					failures <- closeErr
					return
				}
			}
		}()
	}
	wg.Wait()
	close(failures)
	for err := range failures {
		t.Error(err)
	}
	stat, err = local.ReadStat(dir)
	if err != nil || stat.ReadCount != workers*reads {
		t.Fatalf("concurrent read totals: %+v %v", stat, err)
	}
	reader, err := mgr.ReadActualFile(ctx, obj.ID, obj.Name+".md")
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	if err := mgr.WriteActualFile(ctx, obj.ID, "extra.txt", strings.NewReader("payload")); err != nil {
		t.Fatalf("default stream retained object lock: %v", err)
	}
	if err := reader.Close(); err != nil {
		t.Fatal(err)
	}
	if err := mgr.AddTag(ctx, obj.ID, "stat-tag"); err != nil {
		t.Fatal(err)
	}
	if err := mgr.RemoveTag(ctx, obj.ID, "stat-tag"); err != nil {
		t.Fatal(err)
	}
	before, err := local.ReadStat(dir)
	if err != nil || before.WriteCount != 4 {
		t.Fatalf("write totals: %+v %v", before, err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	mgr.recordRead(ctx, obj, nil)
	after, err := local.ReadStat(dir)
	if err != nil || after.ReadCount != before.ReadCount || after.WriteCount != before.WriteCount {
		t.Fatalf("deleted statistics changed: before=%+v after=%+v err=%v", before, after, err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := mgr.GCObjects(ctx, true); err != nil {
		t.Fatal(err)
	}
	mgr.recordRead(ctx, obj, nil)
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatalf("stat resurrected metadata: %v", err)
	}
}

// TestCutoverStatisticCustodyCancellation cancels a reader waiting on exclusive custody.
func TestCutoverStatisticCustodyCancellation(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	obj := createTestObject(t, mgr, "stat-cancel")
	held, err := mgr.acquireExistingObjectLock(obj.ID, true)
	if err != nil {
		t.Fatal(err)
	}
	defer releaseNamespaceLock(held)
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Millisecond)
	defer cancel()
	lock, err := mgr.acquireStatisticCustody(ctx, obj.ID)
	if lock != nil {
		releaseNamespaceLock(lock)
		t.Fatal("acquired conflicting custody")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("custody cancellation: %v", err)
	}
}
