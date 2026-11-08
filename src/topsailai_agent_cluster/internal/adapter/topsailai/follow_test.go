package topsailai

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// fakeFollowRunner records the follow invocation and replays canned lines.
type fakeFollowRunner struct {
	args  []string
	lines []string
	err   error
}

func (f *fakeFollowRunner) Follow(_ context.Context, _ string, args []string, emit func(string) error) error {
	f.args = append([]string(nil), args...)
	for _, line := range f.lines {
		if err := emit(line); err != nil {
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

func TestFollowOutputStreamsLinesWithoutJSON(t *testing.T) {
	runner := &fakeFollowRunner{lines: []string{"first", "second"}}
	a := newFollowAdapter(t, runner)
	mapper := a.mapper.(*fakeMapper)
	if _, err := mapper.GetOrCreateResourceID(context.Background(), "a1", "provider-key", 0); err != nil {
		t.Fatal(err)
	}
	var chunks []protocol.OutputChunk
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key", Generation: "g", MaxLines: 50}, func(chunk protocol.OutputChunk) error {
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
		a := newFollowAdapter(t, runner)
		mapper := a.mapper.(*fakeMapper)
		if _, err := mapper.GetOrCreateResourceID(context.Background(), "a1", "provider-key", 0); err != nil {
			t.Fatal(err)
		}
		if err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key", MaxLines: maxLines}, func(protocol.OutputChunk) error { return nil }); err != nil {
			t.Fatalf("follow: %v", err)
		}
		if !strings.Contains(strings.Join(runner.args, " "), "-n 20") {
			t.Fatalf("maxLines=%d args=%v want default tail 20", maxLines, runner.args)
		}
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
	a := newFollowAdapter(t, runner)
	mapper := a.mapper.(*fakeMapper)
	if _, err := mapper.GetOrCreateResourceID(context.Background(), "a1", "provider-key", 0); err != nil {
		t.Fatal(err)
	}
	stop := errors.New("consumer stopped")
	err := a.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "res_provider-key"}, func(protocol.OutputChunk) error { return stop })
	if !errors.Is(err, stop) {
		t.Fatalf("err=%v want consumer stop", err)
	}
}

func TestFollowOutputPropagatesRunnerError(t *testing.T) {
	runner := &fakeFollowRunner{err: errors.New("provider stream failed")}
	a := newFollowAdapter(t, runner)
	mapper := a.mapper.(*fakeMapper)
	if _, err := mapper.GetOrCreateResourceID(context.Background(), "a1", "provider-key", 0); err != nil {
		t.Fatal(err)
	}
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
	var lines []string
	err := scanFollowLines(strings.NewReader("one\ntwo\npartial"), func(line string) error {
		lines = append(lines, line)
		return nil
	})
	if err != nil {
		t.Fatalf("scan: %v", err)
	}
	// bufio.Scanner yields the trailing unterminated record at EOF, so the
	// consumer still receives it, but only after the stream ended.
	if len(lines) != 3 || lines[2] != "partial" {
		t.Fatalf("lines=%v", lines)
	}
}

func TestScanFollowLinesPropagatesConsumerStop(t *testing.T) {
	stop := errors.New("stop")
	err := scanFollowLines(strings.NewReader("one\ntwo\n"), func(string) error { return stop })
	if !errors.Is(err, stop) {
		t.Fatalf("err=%v want stop", err)
	}
}

func TestScanFollowLinesRejectsOversizedRecord(t *testing.T) {
	huge := strings.Repeat("x", followMaxLineBytes+1)
	err := scanFollowLines(strings.NewReader(huge+"\n"), func(string) error { return nil })
	if err == nil {
		t.Fatal("oversized record was accepted")
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
