package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestMessagesCellRendersTwoCounts pins the cell projection. The two counts are
// rendered as data1/data2 in one cell, and an unmeasured row renders a dash
// rather than "0/0", because zero is a measurement nobody made.
func TestMessagesCellRendersTwoCounts(t *testing.T) {
	for _, tc := range []struct {
		name string
		row  SessionRow
		want string
	}{
		{
			name: "unmeasured row is a dash",
			row:  SessionRow{},
			want: "-",
		},
		{
			name: "measured row renders inbound then outbound",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 7, Outbound: 3}},
			want: "7/3",
		},
		{
			name: "zero counts are a real measurement",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 0, Outbound: 0}},
			want: "0/0",
		},
		{
			name: "large counts are not abbreviated",
			row:  SessionRow{Messages: &protocol.MessageCounts{Inbound: 1234567, Outbound: 89}},
			want: "1234567/89",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := messagesCell(tc.row); got != tc.want {
				t.Fatalf("messagesCell=%q want=%q", got, tc.want)
			}
		})
	}
}

// TestMessagesColumnFollowsDrive pins the column position. The counts sit
// directly after DRIVER so the runtime facts about one session are read
// together, and the header is the field name the human asked for.
func TestMessagesColumnFollowsDrive(t *testing.T) {
	index := -1
	for position, column := range allColumns {
		if column.key == columnMessages {
			index = position
		}
	}
	if index < 0 {
		t.Fatal("messages column is missing from allColumns")
	}
	if allColumns[index-1].key != columnDrive {
		t.Fatalf("messages column follows %q, want %q", allColumns[index-1].key, columnDrive)
	}
	if allColumns[index].header != "MESSAGES" {
		t.Fatalf("messages header=%q want=MESSAGES", allColumns[index].header)
	}
}

// TestMessagesColumnRendersInTable proves the column reaches the rendered table
// and that an unmeasured row renders a dash rather than an empty cell.
func TestMessagesColumnRendersInTable(t *testing.T) {
	var out, errors strings.Builder
	rows := []SessionRow{
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		{EndpointID: "endpoint-1", EndpointLabel: "host-1", ClusterSessionID: "res_2", ProviderSessionID: "provider-session-2", State: "running", CollectionStatus: protocol.CollectionSucceeded, Messages: &protocol.MessageCounts{Inbound: 7, Outbound: 3}},
	}
	if err := RenderTable(&out, &errors, rows, nil, TableOptions{Location: time.UTC}); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(out.String(), "\n"), "\n")
	headerCells := strings.Split(lines[1], " │ ")
	messagesIndex := -1
	for position, cell := range headerCells {
		if strings.TrimSpace(cell) == "MESSAGES" {
			messagesIndex = position
		}
	}
	if messagesIndex < 0 {
		t.Fatalf("rendered header has no MESSAGES column: %q", lines[1])
	}
	absent := strings.Split(lines[3], " │ ")
	if got := strings.TrimSpace(absent[messagesIndex]); got != "-" {
		t.Fatalf("unmeasured messages cell=%q want=-", got)
	}
	present := strings.Split(lines[4], " │ ")
	if got := strings.TrimSpace(present[messagesIndex]); got != "7/3" {
		t.Fatalf("measured messages cell=%q want=7/3", got)
	}
}

// metricsStubAPI is a CommandAPI that also implements metricsReader, so the
// enrichment seam can be exercised without a real client.
type metricsStubAPI struct {
	CommandAPI

	mutex  sync.Mutex
	calls  []string
	counts map[string]protocol.MessageCounts
	fail   map[string]error
	code   map[string]string
}

// GetMetrics records the queried session and returns the configured outcome.
func (s *metricsStubAPI) GetMetrics(_ context.Context, endpointID, sessionID string) (protocol.SessionMetrics, error) {
	s.mutex.Lock()
	s.calls = append(s.calls, endpointID+"/"+sessionID)
	s.mutex.Unlock()
	if err, ok := s.fail[sessionID]; ok {
		return protocol.SessionMetrics{}, err
	}
	if code, ok := s.code[sessionID]; ok {
		return protocol.SessionMetrics{ErrorCode: code}, nil
	}
	return protocol.SessionMetrics{Messages: s.counts[sessionID]}, nil
}

// queried returns the recorded calls in a stable order.
func (s *metricsStubAPI) queried() []string {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	return append([]string(nil), s.calls...)
}

// TestMetricsEnricherIsNilWithoutTheCapability proves a client that cannot read
// counts gets no closure at all, so the renderer skips enrichment instead of
// treating every row as measured.
func TestMetricsEnricherIsNilWithoutTheCapability(t *testing.T) {
	if got := MetricsEnricher(context.Background(), nil); got != nil {
		t.Fatalf("enricher without the capability is not nil")
	}
}

// TestMetricsEnricherMeasuresOnlyRenderedRows proves the seam reads exactly the
// rows it is handed. A filtered or brief table must never pay for a row it does
// not print, and a row with no provider session identifier cannot be addressed
// at all.
func TestMetricsEnricherMeasuresOnlyRenderedRows(t *testing.T) {
	api := &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{"provider-session-1": {Inbound: 7, Outbound: 3}},
		fail:   map[string]error{},
		code:   map[string]string{},
	}
	rows := []SessionRow{
		{EndpointID: "endpoint-1", ProviderSessionID: "provider-session-1"},
		{EndpointID: "endpoint-1", ProviderSessionID: ""},
	}
	MetricsEnricher(context.Background(), api)(rows)
	if got, want := strings.Join(api.queried(), ","), "endpoint-1/provider-session-1"; got != want {
		t.Fatalf("queried=%s want=%s", got, want)
	}
	if rows[0].Messages == nil || rows[0].Messages.Inbound != 7 || rows[0].Messages.Outbound != 3 {
		t.Fatalf("measured row counts=%+v", rows[0].Messages)
	}
	if rows[1].Messages != nil {
		t.Fatalf("unaddressable row was measured: %+v", rows[1].Messages)
	}
}

// TestMetricsEnricherLeavesFailedRowsUnmeasured proves a failed read never
// becomes a zero measurement. The table is built from committed inventory, so a
// live count is an addition to it and a failure must cost one cell, not the
// command and not a false zero.
func TestMetricsEnricherLeavesFailedRowsUnmeasured(t *testing.T) {
	api := &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{"provider-session-1": {Inbound: 7, Outbound: 3}},
		fail:   map[string]error{"provider-session-2": errors.New("transport failure")},
		code:   map[string]string{"provider-session-3": protocol.MetricsSessionNotFound},
	}
	rows := []SessionRow{
		{EndpointID: "endpoint-1", ProviderSessionID: "provider-session-1"},
		{EndpointID: "endpoint-1", ProviderSessionID: "provider-session-2"},
		{EndpointID: "endpoint-1", ProviderSessionID: "provider-session-3"},
	}
	MetricsEnricher(context.Background(), api)(rows)
	if rows[0].Messages == nil {
		t.Fatal("healthy row was not measured")
	}
	if rows[1].Messages != nil {
		t.Fatalf("transport failure produced counts: %+v", rows[1].Messages)
	}
	if rows[2].Messages != nil {
		t.Fatalf("provider error code produced counts: %+v", rows[2].Messages)
	}
}

// TestMetricsEnricherBoundsTheRowsItReads proves one list render cannot become
// one provider call per session in the fleet. The rows beyond the bound stay
// unmeasured, which is an honest value rather than a wrong one.
func TestMetricsEnricherBoundsTheRowsItReads(t *testing.T) {
	api := &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{},
		fail:   map[string]error{},
		code:   map[string]string{},
	}
	rows := make([]SessionRow, maxMetricsRows+5)
	for index := range rows {
		rows[index] = SessionRow{EndpointID: "endpoint-1", ProviderSessionID: "provider-session-" + strings.Repeat("x", index+1)}
	}
	MetricsEnricher(context.Background(), api)(rows)
	if got := len(api.queried()); got != maxMetricsRows {
		t.Fatalf("queried %d rows, want the bound %d", got, maxMetricsRows)
	}
	for index := maxMetricsRows; index < len(rows); index++ {
		if rows[index].Messages != nil {
			t.Fatalf("row %d beyond the bound was measured", index)
		}
	}
}

// TestListRenderEnrichesButWatchDoesNot proves the seam is wired only where the
// human asked for it. `list` shows the counts; `watch` is a periodic redraw and
// must never start a provider read per tick.
//
// Both cases drive the real render entry point, because the seam lives in
// renderListRows rather than in RenderTable. A test that called RenderTable
// directly would pass whether or not the wiring existed.
func TestListRenderEnrichesButWatchDoesNot(t *testing.T) {
	api := &metricsStubAPI{
		counts: map[string]protocol.MessageCounts{"provider-session-1": {Inbound: 7, Outbound: 3}},
		fail:   map[string]error{},
		code:   map[string]string{},
	}
	loaded := reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", DisplayName: "host-1", ConnectionState: "online"}},
		reports: map[string]protocol.InventoryReport{"endpoint-1": {
			CollectionStatus: protocol.CollectionSucceeded,
			Sessions: []protocol.Session{{
				ClusterSessionID:  "res_1",
				ProviderSessionID: "provider-session-1",
				State:             "running",
			}},
		}},
		errors: map[string]error{},
	}

	// A watch-style render passes no enricher, so nothing is read.
	var out, diagnostics strings.Builder
	if err := renderListRows(&out, &diagnostics, loaded, "", false, TableOptions{Location: time.UTC}); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if got := api.queried(); len(got) != 0 {
		t.Fatalf("render without an enricher read counts: %v", got)
	}
	if strings.Contains(out.String(), "7/3") {
		t.Fatalf("render without an enricher printed counts: %q", out.String())
	}

	// A list-style render passes the enricher, so the row is measured and the
	// counts reach the printed bytes.
	out.Reset()
	diagnostics.Reset()
	options := TableOptions{Location: time.UTC, EnrichRows: MetricsEnricher(context.Background(), api)}
	if err := renderListRows(&out, &diagnostics, loaded, "", false, options); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	if got := len(api.queried()); got != 1 {
		t.Fatalf("list render read %d rows, want 1", got)
	}
	if !strings.Contains(out.String(), "7/3") {
		t.Fatalf("list render did not print the counts: %q", out.String())
	}
}

// TestTableOptionsForNeverEnriches proves the shared option builder leaves the
// enrichment seam unset. `watch` and `refresh` build their options through this
// function and never assign the seam, so a periodic redraw cannot start one
// provider read per tick. Only the list surfaces opt in explicitly.
func TestTableOptionsForNeverEnriches(t *testing.T) {
	options := tableOptionsFor(io.Discard, ColorPolicy{}, listArguments{}, nil)
	if options.EnrichRows != nil {
		t.Fatal("tableOptionsFor set EnrichRows, so every periodic redraw would enrich")
	}
}
