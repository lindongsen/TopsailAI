package local

import (
	"fmt"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestCutoverSortStable preserves input order for identical time prefixes.
func TestCutoverSortStable(t *testing.T) {
	for _, ascending := range []bool{true, false} {
		objects := []*models.Object{
			{ID: "a", Path: "2026/1111/1200/a"},
			{ID: "b", Path: "2026/1111/1200/b"},
			{ID: "early", Path: "2026/1111/1100/early"},
			{ID: "late", Path: "2026/1111/1300/late"},
		}
		SortObjectsByTimePath(objects, ascending)
		positions := map[models.ObjectID]int{}
		for i, obj := range objects {
			positions[obj.ID] = i
		}
		if positions["a"] >= positions["b"] {
			t.Fatalf("equal keys reordered ascending=%v: %v", ascending, positions)
		}
		for i := 1; i < len(objects); i++ {
			cmp := compareTimePath(objects[i-1].Path, objects[i].Path)
			if (ascending && cmp > 0) || (!ascending && cmp < 0) {
				t.Fatalf("incorrect order ascending=%v", ascending)
			}
		}
	}
}

// TestCutoverSortScale validates both directions at the expected collection size.
func TestCutoverSortScale(t *testing.T) {
	const count = 100000
	for _, ascending := range []bool{true, false} {
		objects := make([]*models.Object, count)
		for i := range objects {
			minute := (i * 7919) % 1440
			objects[i] = &models.Object{ID: models.ObjectID(fmt.Sprintf("obj-%d", i)), Path: fmt.Sprintf("2026/1111/%02d%02d/obj-%d", minute/60, minute%60, i)}
		}
		start := time.Now()
		SortObjectsByTimePath(objects, ascending)
		t.Logf("records=%d ascending=%v elapsed=%s", count, ascending, time.Since(start))
		for i := 1; i < count; i++ {
			cmp := compareTimePath(objects[i-1].Path, objects[i].Path)
			if (ascending && cmp > 0) || (!ascending && cmp < 0) {
				t.Fatalf("unordered pair at %d", i)
			}
		}
	}
}
