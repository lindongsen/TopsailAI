package tui

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

var unitCScaleOutput = flag.String("unit-c-scale-output", "", "absolute temporary directory for bounded C14 JSONL samples")

// unitCScaleReport constructs globally unique, bounded session fixtures.
func unitCScaleReport(endpointID string, sessions int) protocol.InventoryReport {
	report := protocol.InventoryReport{SchemaVersion: "1", SourceGeneration: "gen-1", ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	for i := 0; i < sessions; i++ {
		report.Sessions = append(report.Sessions, protocol.Session{SessionID: fmt.Sprintf("%s-session-%06d", endpointID, i), AgentID: endpointID, Generation: "gen-1", AdapterID: "adapter-1", State: "ready", CollectionStatus: protocol.CollectionSucceeded})
	}
	return report
}

// unitCPercentile reports observations without imposing a wall-clock gate.
func unitCPercentile(samples []time.Duration, percentile int) time.Duration {
	ordered := append([]time.Duration(nil), samples...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i] < ordered[j] })
	return ordered[(len(ordered)-1)*percentile/100]
}

// unitCScaleFixture gives each measured call fresh counts over the same immutable large data.
func unitCScaleFixture(endpoints int, sessions int) (*unitCAPI, interactiveState) {
	api := newUnitCAPI()
	api.endpoints = nil
	api.reports = make(map[string]protocol.InventoryReport, endpoints)
	for i := 0; i < endpoints; i++ {
		id := fmt.Sprintf("ep-%03d", i)
		api.endpoints = append(api.endpoints, protocol.Endpoint{EndpointID: id, Hostname: id})
		api.reports[id] = unitCScaleReport(id, sessions/endpoints)
	}
	state := seedUnitCState()
	state.Rows = make(map[int]SessionRow, sessions)
	for i, row := range ListRows(api.endpoints, api.reports, "") {
		row.No = i + 1
		state.Rows[i+1] = row
	}
	return api, state
}

// unitCScaleAPI detaches mutable counts and retained intents, not immutable input fixtures.
func unitCScaleAPI(base *unitCAPI) *unitCAPI {
	api := newUnitCAPI()
	api.endpoints = base.endpoints
	api.reports = base.reports
	return api
}

// unitCScaleWriter emits readiness after successful prompt writes without retaining huge tables.
type unitCScaleWriter struct {
	prompts chan time.Time
	pending string
}

// Write records only exact complete prompt writes; inventory bytes are discarded.
func (w *unitCScaleWriter) Write(p []byte) (int, error) {
	w.pending += string(p)
	if strings.HasSuffix(w.pending, "cluster> ") {
		w.prompts <- time.Now()
		w.pending = ""
	}
	if len(w.pending) > 128 {
		w.pending = w.pending[len(w.pending)-128:]
	}
	return len(p), nil
}

// unitCScaleRunner measures a real large startup and owned field cancellation lifecycle.
func unitCScaleRunner(t *testing.T, base *unitCAPI) (time.Duration, time.Duration) {
	t.Helper()
	api := unitCScaleAPI(base)
	reader := newUnitCTicketReader()
	writer := &unitCScaleWriter{prompts: make(chan time.Time, 4)}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	joined := make(chan struct{})
	var once sync.Once
	cleanup := func() { once.Do(func() { cancel(); _ = reader.Close(); <-joined }) }
	defer cleanup()
	started := time.Now()
	go func() {
		defer close(joined)
		done <- RunInteractive(ctx, api, reader, writer, io.Discard, InteractiveOptions{CloseInput: true})
	}()
	main := <-writer.prompts
	ticket := <-reader.entered
	if err := unitCReply(ticket, "start\n", nil); err != nil {
		t.Fatal(err)
	}
	<-writer.prompts
	pending := <-reader.entered
	if pending.n != 2 {
		t.Fatalf("C14 field readiness ticket=%d", pending.n)
	}
	before, _ := api.snapshot()
	when := time.Now()
	cancel()
	err := <-done
	elapsed := time.Since(when)
	if err != ctx.Err() {
		t.Fatalf("C14 runner error=%v", err)
	}
	after, intents := api.snapshot()
	if before != (unitCAPICounts{List: 1, Inventory: len(base.endpoints)}) || unitCAPIAdd(before, after) != (unitCAPICounts{}) || len(intents) != 0 {
		t.Fatalf("C14 runner calls: before=%+v after=%+v intents=%v", before, after, intents)
	}
	return main.Sub(started), elapsed
}

// TestUnitCStartScaleCostContract uses the actual large Rows and inventory in every flow.
func TestUnitCStartScaleCostContract(t *testing.T) {
	dir := *unitCScaleOutput
	if dir == "" {
		dir = t.TempDir()
	}
	if !filepath.IsAbs(dir) {
		t.Fatal("C14 sample directory must be absolute")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	for _, size := range []struct{ endpoints, sessions int }{{10, 1000}, {100, 10000}} {
		t.Run(fmt.Sprintf("endpoints-%d-sessions-%d", size.endpoints, size.sessions), func(t *testing.T) {
			base, seed := unitCScaleFixture(size.endpoints, size.sessions)
			if len(seed.Rows) != size.sessions {
				t.Fatal("C14 missing large rows")
			}
			file, err := os.Create(filepath.Join(dir, fmt.Sprintf("samples-%d.jsonl", size.sessions)))
			if err != nil {
				t.Fatal(err)
			}
			defer file.Close()
			enc := json.NewEncoder(file)
			record := func(mode string, sample int, duration time.Duration, counts unitCAPICounts) {
				if err := enc.Encode(map[string]any{"mode": mode, "sample": sample, "endpoints": size.endpoints, "sessions": size.sessions, "duration_ns": duration.Nanoseconds(), "counts": counts}); err != nil {
					t.Fatal(err)
				}
			}
			for _, mode := range []string{"cancel", "complete"} {
				samples := make([]time.Duration, 0, 100)
				for sample := -10; sample < 100; sample++ {
					api := unitCScaleAPI(base)
					state := cloneUnitCState(seed)
					before := cloneUnitCState(state)
					lines := make(chan lineReadResult, 4)
					for _, v := range []string{"ep-000", "compat-resource", "profile-1"} {
						lines <- lineReadResult{line: v}
					}
					final := "revision-1"
					if mode == "cancel" {
						final = "cancel"
					}
					lines <- lineReadResult{line: final}
					started := time.Now()
					exit, err := executeInteractiveLine(context.Background(), api, &state, "start", lines, io.Discard, io.Discard, io.Discard, InteractiveOptions{})
					duration := time.Since(started)
					counts, intents := api.snapshot()
					want := unitCAPICounts{}
					if mode == "complete" {
						want = unitCAPICounts{Capability: 1, Admit: 1, Command: 1}
						before.commandID = "unit-c-command"
					}
					if exit || err != nil || counts != want || len(intents) != want.Admit || !reflect.DeepEqual(state, before) || len(state.Rows) != size.sessions {
						t.Fatalf("C14 %s sample%d: err=%v counts=%+v want=%+v intents=%d rows=%d stateEqual=%v", mode, sample, err, counts, want, len(intents), len(state.Rows), reflect.DeepEqual(state, before))
					}
					if sample >= 0 {
						samples = append(samples, duration)
						record(mode, sample, duration, counts)
					}
				}
				t.Logf("scale=%d mode=%s samples=%d median=%s p95=%s", size.sessions, mode, len(samples), unitCPercentile(samples, 50), unitCPercentile(samples, 95))
			}
			history := cloneUnitCState(seed)
			before := cloneUnitCState(history)
			api := unitCScaleAPI(base)
			for i := 0; i < 100; i++ {
				if exit, err := executeInteractiveLine(context.Background(), api, &history, "start", unitCStartCancelLines(startFieldRevision), io.Discard, io.Discard, io.Discard, InteractiveOptions{}); exit || err != nil {
					t.Fatalf("C14 history: %v", err)
				}
			}
			if !reflect.DeepEqual(history, before) {
				t.Fatal("C14 accumulated state")
			}
			assertNoAPIActivity(t, api)
			for i := 0; i < 100; i++ {
				startup, cancel := unitCScaleRunner(t, base)
				record("runner-startup", i, startup, unitCAPICounts{List: 1, Inventory: size.endpoints})
				record("runner-cancel", i, cancel, unitCAPICounts{})
			}
			if err := file.Sync(); err != nil {
				t.Fatal(err)
			}
			t.Logf("C14 actual Rows=%d endpoints=%d JSONL=%s", len(seed.Rows), len(base.endpoints), file.Name())
		})
	}
}
