package topsailai

import (
	"context"
	"errors"
	"strings"
	"testing"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// fakeFollowRunner records the follow invocation and replays canned records.
type fakeFollowRunner struct {
	args  []string
	limit int
	lines []string
	err   error
}

func (f *fakeFollowRunner) Follow(_ context.Context, _ string, args []string, limit int, emit func(followRecord) error) error {
	f.args = append([]string(nil), args...)
	f.limit = limit
	for _, line := range f.lines {
		if err := emit(followRecord{Line: line}); err != nil {
			return err
		}
	}
	return f.err
}

// newFollowAdapter builds an adapter whose follow runner is the supplied fake.
func newFollowAdapter(t *testing.T, runner followRunner) *Adapter {
	t.Helper()
	result, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 1024, ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
	}}, &fakeRunner{})
	if err != nil {
		t.Fatal(err)
	}
	result.followRunner = runner
	return result
}

// mappedFollowAdapter builds a follow adapter with one resolvable resource.
func mappedFollowAdapter(t *testing.T, runner followRunner) *Adapter {
	t.Helper()
	a := newFollowAdapter(t, runner)
	mapper := a.mapper.(*fakeMapper)
	if _, err := mapper.GetOrCreateResourceID(context.Background(), "a1", "provider-key", 0); err != nil {
		t.Fatal(err)
	}
	return a
}

func TestFollowOutputStreamsLinesWithoutJSON(t *testing.T) {
	runner := &fakeFollowRunner{lines: []string{"first", "second"}}
	a := mappedFollowAdapter(t, runner)
	var chunks []protocol.OutputChunk
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key", ProviderGeneration: "g", MaxLines: 50}, func(chunk protocol.OutputChunk) error {
		chunks = append(chunks, chunk)
		return nil
	})
	if err != nil {
		t.Fatalf("follow: %v", err)
	}
	if len(chunks) != 2 {
		t.Fatalf("chunks=%d want 2", len(chunks))
	}
	if chunks[0].Lines[0] != "first" || chunks[1].Lines[0] != "second" {
		t.Fatalf("chunks=%#v", chunks)
	}
	for _, chunk := range chunks {
		if chunk.ObservedAtMS == 0 {
			t.Fatalf("chunk has no observation time: %#v", chunk)
		}
		if chunk.Truncated {
			t.Fatalf("chunk is labelled truncated: %#v", chunk)
		}
	}
	joined := strings.Join(runner.args, " ")
	if !strings.Contains(joined, "--follow") {
		t.Fatalf("args=%v want --follow", runner.args)
	}
	// The provider rejects --json together with --follow, so the follow path
	// must never pass it.
	if strings.Contains(joined, "--json") {
		t.Fatalf("args=%v must not contain --json", runner.args)
	}
	if !strings.Contains(joined, "-n 50") {
		t.Fatalf("args=%v want the requested tail size", runner.args)
	}
}

func TestFollowOutputDefaultsTailSize(t *testing.T) {
	for _, maxLines := range []int{0, -1, 10001} {
		runner := &fakeFollowRunner{}
		a := mappedFollowAdapter(t, runner)
		if err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key", MaxLines: maxLines}, func(protocol.OutputChunk) error { return nil }); err != nil {
			t.Fatalf("follow: %v", err)
		}
		if !strings.Contains(strings.Join(runner.args, " "), "-n 20") {
			t.Fatalf("maxLines=%d args=%v want default tail 20", maxLines, runner.args)
		}
	}
}

// TestFollowOutputHonoursMaxBytes proves the requested byte budget reaches the
// runner. Before this was wired the adapter ignored MaxBytes entirely, so a
// caller that asked for a small budget silently received the default one.
func TestFollowOutputHonoursMaxBytes(t *testing.T) {
	cases := []struct {
		name     string
		maxBytes int
		want     int
	}{
		{name: "explicit budget", maxBytes: 1024, want: 1024},
		{name: "absent budget uses the default", maxBytes: 0, want: followDefaultRecordBytes},
		{name: "negative budget uses the default", maxBytes: -1, want: followDefaultRecordBytes},
		{name: "oversized budget is clamped", maxBytes: 10 << 20, want: followMaxRecordBytes},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &fakeFollowRunner{}
			a := mappedFollowAdapter(t, runner)
			if err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key", MaxBytes: testCase.maxBytes}, func(protocol.OutputChunk) error { return nil }); err != nil {
				t.Fatalf("follow: %v", err)
			}
			if runner.limit != testCase.want {
				t.Fatalf("limit=%d want %d", runner.limit, testCase.want)
			}
		})
	}
}

func TestFollowOutputRejectsUnknownResource(t *testing.T) {
	a := newFollowAdapter(t, &fakeFollowRunner{})
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "missing"}, func(protocol.OutputChunk) error { return nil })
	if err == nil {
		t.Fatal("unknown resource was accepted")
	}
}

func TestFollowOutputPropagatesConsumerStop(t *testing.T) {
	runner := &fakeFollowRunner{lines: []string{"a", "b"}}
	a := mappedFollowAdapter(t, runner)
	stop := errors.New("consumer stopped")
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key"}, func(protocol.OutputChunk) error { return stop })
	if !errors.Is(err, stop) {
		t.Fatalf("err=%v want consumer stop", err)
	}
}

func TestFollowOutputPropagatesRunnerError(t *testing.T) {
	runner := &fakeFollowRunner{err: errors.New("provider stream failed")}
	a := mappedFollowAdapter(t, runner)
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key"}, func(protocol.OutputChunk) error { return nil })
	if err == nil {
		t.Fatal("runner error was swallowed")
	}
}

func TestFollowEnvironmentForcesUnbuffered(t *testing.T) {
	// An inherited empty or "0" value would silently restore buffering, so the
	// variable must be replaced rather than merely added when absent.
	for _, base := range [][]string{{"PATH=/bin"}, {"PYTHONUNBUFFERED=0", "PATH=/bin"}, {"PYTHONUNBUFFERED=", "PATH=/bin"}} {
		environment := followEnvironment("/usr/bin/provider", base)
		count := 0
		for _, entry := range environment {
			if strings.HasPrefix(entry, "PYTHONUNBUFFERED=") {
				count++
				if entry != "PYTHONUNBUFFERED=1" {
					t.Fatalf("base=%v entry=%q want PYTHONUNBUFFERED=1", base, entry)
				}
			}
		}
		if count != 1 {
			t.Fatalf("base=%v has %d PYTHONUNBUFFERED entries", base, count)
		}
	}
}

func TestScanFollowLinesDeliversCompleteRecordsOnly(t *testing.T) {
	var records []followRecord
	err := scanFollowLines(strings.NewReader("one\ntwo\npartial"), followDefaultRecordBytes, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	// A trailing unterminated record is still delivered, but only at EOF.
	if len(records) != 3 || records[2].Line != "partial" {
		t.Fatalf("records=%#v", records)
	}
	for _, record := range records {
		if record.Truncated {
			t.Fatalf("record is labelled truncated: %#v", record)
		}
	}
}

func TestScanFollowLinesPropagatesConsumerStop(t *testing.T) {
	stop := errors.New("stop")
	err := scanFollowLines(strings.NewReader("one\ntwo\n"), followDefaultRecordBytes, func(followRecord) error { return stop })
	if !errors.Is(err, stop) {
		t.Fatalf("err=%v want stop", err)
	}
}

// TestScanFollowLinesTruncatesOversizedRecord proves an oversized record is
// shortened and labelled instead of ending the stream. Ending the stream would
// report a provider failure for what is only a long line, and the operator would
// lose every later record.
func TestScanFollowLinesTruncatesOversizedRecord(t *testing.T) {
	huge := strings.Repeat("x", 100)
	var records []followRecord
	err := scanFollowLines(strings.NewReader(huge+"\nafter\n"), 16, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(records) != 2 {
		t.Fatalf("records=%d want 2, the stream must continue after an oversized record", len(records))
	}
	if !records[0].Truncated {
		t.Fatalf("oversized record is not labelled truncated: %#v", records[0])
	}
	if len(records[0].Line) != 16 {
		t.Fatalf("truncated length=%d want 16", len(records[0].Line))
	}
	if records[1].Line != "after" || records[1].Truncated {
		t.Fatalf("record after the oversized one=%#v want the intact next record", records[1])
	}
}

// TestScanFollowLinesTruncatesOnRuneBoundary proves truncation never splits a
// multi-byte character, because a half rune would render as a replacement
// character and corrupt the operator's view.
func TestScanFollowLinesTruncatesOnRuneBoundary(t *testing.T) {
	// Each "中" is three bytes, so a 4-byte budget can hold only one rune.
	var records []followRecord
	err := scanFollowLines(strings.NewReader("中中中\n"), 4, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(records) != 1 || !records[0].Truncated {
		t.Fatalf("records=%#v want one truncated record", records)
	}
	if !utf8.ValidString(records[0].Line) {
		t.Fatalf("truncated record is not valid UTF-8: %q", records[0].Line)
	}
	if records[0].Line != "中" {
		t.Fatalf("truncated record=%q want one whole rune", records[0].Line)
	}
}

// TestScanFollowLinesKeepsBlankRecords proves a blank line is a record, not an
// end of stream, so a provider that prints an empty line does not stop delivery.
func TestScanFollowLinesKeepsBlankRecords(t *testing.T) {
	var records []followRecord
	err := scanFollowLines(strings.NewReader("\nvalue\n"), followDefaultRecordBytes, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(records) != 2 || records[0].Line != "" || records[1].Line != "value" {
		t.Fatalf("records=%#v want a blank record then the value", records)
	}
}

func TestAdapterAdvertisesOutputFollow(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, capability := range descriptor.Capabilities.Capabilities {
		if capability.Name == protocol.OperationOutputFollow {
			found = true
		}
	}
	if !found {
		t.Fatal("output.follow is not advertised")
	}
}

func TestAdapterSatisfiesEndpointFollowerContract(t *testing.T) {
	// The Endpoint type-asserts its executor to a follower interface. A signature
	// drift here would silently turn every follow into an unsupported response.
	var _ interface {
		FollowOutput(context.Context, protocol.OutputFollowRequest, func(protocol.OutputChunk) error) error
	} = (*Adapter)(nil)
	var _ adapter.OutputFollower = (*Adapter)(nil)
}

// TestScanFollowLinesKeepsRecordLongerThanTheReadBuffer proves a record that
// exceeds the internal read buffer is still delivered intact when it fits the
// byte budget. The reader returns a partial slice with ErrBufferFull in that
// case, so a scanner that treated that error as a failure would drop a long but
// legal record.
func TestScanFollowLinesKeepsRecordLongerThanTheReadBuffer(t *testing.T) {
	long := strings.Repeat("y", 100<<10)
	var records []followRecord
	err := scanFollowLines(strings.NewReader(long+"\nnext\n"), followMaxRecordBytes, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(records) != 2 {
		t.Fatalf("records=%d want 2", len(records))
	}
	if records[0].Line != long || records[0].Truncated {
		t.Fatalf("long record length=%d truncated=%t want the intact record", len(records[0].Line), records[0].Truncated)
	}
	if records[1].Line != "next" {
		t.Fatalf("record after the long one=%q", records[1].Line)
	}
}

// TestScanFollowLinesTruncatesRecordSpanningTheReadBuffer proves truncation also
// works when the oversized record arrives in several buffer-sized pieces, so the
// budget is enforced on the whole record rather than on one read.
func TestScanFollowLinesTruncatesRecordSpanningTheReadBuffer(t *testing.T) {
	huge := strings.Repeat("z", 200<<10)
	var records []followRecord
	err := scanFollowLines(strings.NewReader(huge+"\nafter\n"), 1024, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(records) != 2 {
		t.Fatalf("records=%d want 2, the stream must continue", len(records))
	}
	if !records[0].Truncated || len(records[0].Line) != 1024 {
		t.Fatalf("truncated=%t length=%d want a 1024-byte truncated record", records[0].Truncated, len(records[0].Line))
	}
	if records[1].Line != "after" {
		t.Fatalf("record after the oversized one=%q", records[1].Line)
	}
}

// TestTruncateUTF8HandlesNonPositiveLimit proves a non-positive budget yields no
// bytes instead of panicking or returning the whole record.
func TestTruncateUTF8HandlesNonPositiveLimit(t *testing.T) {
	for _, limit := range []int{0, -1} {
		if got := truncateUTF8([]byte("data"), limit); len(got) != 0 {
			t.Fatalf("limit=%d got=%q want empty", limit, got)
		}
	}
}

// TestTruncateUTF8KeepsDataWithinTheLimit proves a record that already fits is
// returned unchanged, so the common path never copies or shortens data.
func TestTruncateUTF8KeepsDataWithinTheLimit(t *testing.T) {
	if got := truncateUTF8([]byte("data"), 4); string(got) != "data" {
		t.Fatalf("got=%q want the unchanged record", got)
	}
}

// failingReader returns one chunk and then a hard read error, so the error path
// that is not EOF is exercised.
type failingReader struct {
	payload []byte
	err     error
	done    bool
}

func (r *failingReader) Read(buffer []byte) (int, error) {
	if r.done {
		return 0, r.err
	}
	r.done = true
	return copy(buffer, r.payload), nil
}

// TestScanFollowLinesReportsReadError proves a genuine read failure is reported
// instead of being mistaken for a clean end of stream.
func TestScanFollowLinesReportsReadError(t *testing.T) {
	broken := errors.New("pipe broke")
	var records []followRecord
	err := scanFollowLines(&failingReader{payload: []byte("one\n"), err: broken}, followDefaultRecordBytes, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if !errors.Is(err, broken) {
		t.Fatalf("err=%v want the read error", err)
	}
	if len(records) != 1 || records[0].Line != "one" {
		t.Fatalf("records=%#v want the record read before the failure", records)
	}
}

// TestScanFollowLinesNormalizesTheBudget proves the defensive budget clamp works
// even when a caller bypasses the adapter normalization, so an absent or absurd
// budget can never mean "unbounded".
func TestScanFollowLinesNormalizesTheBudget(t *testing.T) {
	huge := strings.Repeat("q", followMaxRecordBytes+10)
	for _, limit := range []int{0, -5, followMaxRecordBytes * 4} {
		var records []followRecord
		err := scanFollowLines(strings.NewReader(huge+"\n"), limit, func(record followRecord) error {
			records = append(records, record)
			return nil
		})
		if err != nil {
			t.Fatalf("limit=%d scan: %v", limit, err)
		}
		if len(records) != 1 || !records[0].Truncated {
			t.Fatalf("limit=%d records=%#v want one truncated record", limit, records)
		}
		if len(records[0].Line) > followMaxRecordBytes {
			t.Fatalf("limit=%d length=%d exceeds the absolute ceiling", limit, len(records[0].Line))
		}
	}
}
