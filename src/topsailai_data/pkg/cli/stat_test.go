package cli

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/models"
)

func setObjectStat(t *testing.T, obj *models.Object, readCount, writeCount uint64, readAt time.Time) {
	t.Helper()
	stat := &models.ObjectStat{
		SchemaVersion: models.ObjectStatSchemaVersion,
		ReadCount:     readCount,
		WriteCount:    writeCount,
	}
	if !readAt.IsZero() {
		stat.LastReadAt = &readAt
	}
	if err := local.WriteStat(obj.DataRef, stat); err != nil {
		t.Fatalf("write stat: %v", err)
	}
}

func TestStatOneAndShowSection(t *testing.T) {
	mgr, _, ctx := setupManager(t)
	obj := createTestObject(t, ctx, mgr, "observed")
	when := time.Date(2026, 8, 24, 9, 30, 0, 0, time.Local)
	setObjectStat(t, obj, 7, 3, when)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"stat", string(obj.ID), "--format", "json"}); err != nil {
			t.Fatalf("stat: %v", err)
		}
	})
	var stat models.ObjectStat
	if err := json.Unmarshal([]byte(out), &stat); err != nil {
		t.Fatalf("decode stat: %v", err)
	}
	if stat.ReadCount != 7 || stat.WriteCount != 3 || stat.LastReadAt == nil {
		t.Fatalf("unexpected stat: %+v", stat)
	}

	out = captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"show", string(obj.ID)}); err != nil {
			t.Fatalf("show: %v", err)
		}
	})
	if !strings.Contains(out, "Stat:") || !strings.Contains(out, "ReadCount:     7") {
		t.Fatalf("show stat section missing: %s", out)
	}
	if strings.Contains(out, ".stat.json") {
		t.Fatalf("show tree exposed stat marker: %s", out)
	}
}

func TestStatTopSortingLimitStatusAndFormats(t *testing.T) {
	mgr, _, ctx := setupManager(t)
	cold := createTestObject(t, ctx, mgr, "cold")
	hot := createTestObject(t, ctx, mgr, "hot")
	deleted := createTestObject(t, ctx, mgr, "deleted-stat")
	setObjectStat(t, cold, 1, 8, time.Now().Add(-time.Hour))
	setObjectStat(t, hot, 9, 2, time.Now())
	setObjectStat(t, deleted, 20, 1, time.Now())
	if err := mgr.DeleteObject(ctx, deleted.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"stat", "top", "--by", "read", "--order", "desc", "--limit", "1", "--format", "json"}); err != nil {
			t.Fatalf("stat top: %v", err)
		}
	})
	var rows []statRankRow
	if err := json.Unmarshal([]byte(out), &rows); err != nil {
		t.Fatalf("decode rows: %v", err)
	}
	if len(rows) != 1 || rows[0].ID != "hot" || rows[0].Rank != 1 {
		t.Fatalf("unexpected ranking: %+v", rows)
	}

	out = captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"stat", "top", "--by", "write", "--order", "asc", "--status", "deleted"}); err != nil {
			t.Fatalf("stat top deleted yaml: %v", err)
		}
	})
	if !strings.Contains(out, "id: deleted-stat") || strings.Contains(out, "id: hot") {
		t.Fatalf("status filtering or yaml output failed: %s", out)
	}
}

func TestListAndSearchWithStat(t *testing.T) {
	mgr, _, ctx := setupManager(t)
	obj := createTestObject(t, ctx, mgr, "listed-stat", "stat-tag")
	setObjectStat(t, obj, 4, 2, time.Now())

	for _, args := range [][]string{{"list", "--with-stat", "--format", "json"}, {"search", "stat-tag", "--with-stat"}} {
		out := captureStdout(t, func() {
			if err := Run(ctx, mgr, args); err != nil {
				t.Fatalf("%v: %v", args, err)
			}
		})
		if !strings.Contains(out, "read_count") || !strings.Contains(out, "write_count") {
			t.Fatalf("%v missing stat fields: %s", args, out)
		}
	}
}

func TestStatTopMissingStatSortsFirstAscending(t *testing.T) {
	mgr, _, ctx := setupManager(t)
	without := createTestObject(t, ctx, mgr, "without-stat")
	with := createTestObject(t, ctx, mgr, "with-stat")
	setObjectStat(t, with, 2, 0, time.Now())
	if err := local.WriteStat(without.DataRef, &models.ObjectStat{}); err != nil {
		t.Fatalf("zero stat: %v", err)
	}

	out := captureStdout(t, func() {
		if err := runStatTop(context.Background(), mgr, []string{"--order", "asc", "--format", "json"}); err != nil {
			t.Fatalf("stat top: %v", err)
		}
	})
	var rows []statRankRow
	if err := json.Unmarshal([]byte(out), &rows); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(rows) < 2 || rows[0].ID != "without-stat" {
		t.Fatalf("zero stat should rank first ascending: %+v", rows)
	}
}
