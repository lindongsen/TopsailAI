package topsailai

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

type fakeRunner struct {
	args  []string
	stdin []byte
	out   []byte
	err   error
}

type fakeMapper struct {
	byKey map[string]ResourceMapping
	byID  map[string]ResourceMapping
}

func newFakeMapper() *fakeMapper {
	return &fakeMapper{byKey: make(map[string]ResourceMapping), byID: make(map[string]ResourceMapping)}
}

func (m *fakeMapper) GetOrCreateResourceID(_ context.Context, adapterID, providerKey string, _ int64) (ResourceMapping, error) {
	if mapping, ok := m.byKey[providerKey]; ok {
		return mapping, nil
	}
	mapping := ResourceMapping{AdapterID: adapterID, ProviderKey: providerKey, ResourceID: "res_" + providerKey}
	m.byKey[providerKey] = mapping
	m.byID[mapping.ResourceID] = mapping
	return mapping, nil
}

func (m *fakeMapper) LookupResourceID(_ context.Context, resourceID string) (ResourceMapping, error) {
	mapping, ok := m.byID[resourceID]
	if !ok {
		return ResourceMapping{}, errors.New("mapping not found")
	}
	return mapping, nil
}

func (f *fakeRunner) Run(_ context.Context, _ string, args []string, stdin []byte) ([]byte, error) {
	f.args = append([]string(nil), args...)
	f.stdin = append([]byte(nil), stdin...)
	return f.out, f.err
}

func newTestAdapter(t *testing.T, runner *fakeRunner) *Adapter {
	t.Helper()
	result, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: 1024, ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
	}}, runner)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestDescribeDeclaresRequiredCapabilities(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if descriptor.Capabilities.Revision == "" {
		t.Fatal("missing capability revision")
	}
	want := map[string]bool{"discover": true, "message.send": true, "context.inject": true, "execution.interrupt": true, "output.read": true, "agent.start": true, "agent.resume": true, "agent.stop": true}
	for _, capability := range descriptor.Capabilities.Capabilities {
		delete(want, capability.Name)
	}
	if len(want) != 0 {
		t.Fatalf("missing capabilities: %v", want)
	}
}
func TestDiscoverUsesOpaqueIDsAndRejectsMalformedOrTruncatedResults(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1","status":"running"}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil || len(result.Sessions) != 1 {
		t.Fatalf("discover: %#v %v", result, err)
	}
	if result.Sessions[0].SessionID == "provider-secret" || result.Sessions[0].Generation != "g1" {
		t.Fatalf("provider identity leaked or generation missing: %#v", result.Sessions[0])
	}
	if !reflect.DeepEqual(runner.args, []string{"workspace", "--format", "json"}) {
		t.Fatalf("unexpected discover argv: %#v", runner.args)
	}

	runner.out = []byte(`{"items":[{"session_id":"s","process_generation":"g"}],"total":2}`)
	result, err = a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil || result.Complete || result.ErrorCode != "discovery_truncated" {
		t.Fatalf("truncation was not explicit: %#v %v", result, err)
	}
	runner.out = []byte(`not-json`)
	if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err == nil {
		t.Fatal("malformed discovery must fail")
	}
}

func TestDiscoverSkipsWorkspaceRowsWithoutGeneration(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"idle-history","status":"idle"},{"session_id":"live-session","process_generation":"g1","status":"running"}],"total":2}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	if len(result.Sessions) != 1 || result.Sessions[0].Generation != "g1" {
		t.Fatalf("routable sessions = %#v, want one generation g1 session", result.Sessions)
	}
	if result.Sessions[0].SessionID != "res_live-session" {
		t.Fatalf("session ID = %q, want opaque mapping", result.Sessions[0].SessionID)
	}
}

func TestDiscoverAcceptsNumericStringAndNullGenerations(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"numeric","process_generation":435912980},{"session_id":"string","process_generation":"g1"},{"session_id":"idle","process_generation":null}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	if len(result.Sessions) != 2 {
		t.Fatalf("session count = %d, want 2: %#v", len(result.Sessions), result.Sessions)
	}
	if result.Sessions[0].SessionID != "res_numeric" || result.Sessions[0].Generation != "435912980" {
		t.Fatalf("numeric session = %#v", result.Sessions[0])
	}
	if result.Sessions[1].SessionID != "res_string" || result.Sessions[1].Generation != "g1" {
		t.Fatalf("string session = %#v", result.Sessions[1])
	}
}

func TestExecuteUsesProviderCLIFlagsAndMessagePayload(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	runner.out = []byte(`{"delivery_state":"submitted"}`)
	target := &protocol.CommandTarget{ResourceID: result.Sessions[0].SessionID, Generation: "g1"}
	payload := []byte(`{"message":"-- -g value with spaces \"quotes\"\nnext"}`)
	_, err = a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c1", Operation: "send", Target: target, Payload: payload}})
	if err != nil {
		t.Fatal(err)
	}
	wantArgs := []string{"runtime", "send", "-s", "provider-secret", "-m", "-- -g value with spaces \"quotes\"\nnext", "--json"}
	if !reflect.DeepEqual(runner.args, wantArgs) {
		t.Fatalf("unexpected argv: %#v, want %#v", runner.args, wantArgs)
	}
	if len(runner.stdin) != 0 {
		t.Fatalf("payload unexpectedly went to stdin: %q", runner.stdin)
	}
}

func TestStopRequiresGenerationAndPreservesSignalSemantics(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
	a := newTestAdapter(t, runner)
	_, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	id := "res_provider-secret"
	runner.out = []byte(`{"signal_sent":true,"exit_confirmed":false}`)
	_, err = a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c1", Operation: "agent.stop", Target: &protocol.CommandTarget{ResourceID: id}}})
	if err == nil || !contains(err.Error(), "generation") {
		t.Fatalf("missing generation was not rejected: %v", err)
	}
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c2", Operation: "agent.stop", Target: &protocol.CommandTarget{ResourceID: id, Generation: "g1"}}})
	if err != nil || result.Receipt.EffectCertainty != protocol.EffectAcknowledged || result.Receipt.DeliveryBoundary != protocol.DeliverySignalSent || result.Receipt.ExitConfirmed {
		t.Fatalf("stop signal semantics were not preserved: %#v %v", result, err)
	}
}

func TestTopsailaiAdapterExecutesDeclaredInterruptOperation(t *testing.T) {
	for _, testCase := range []struct {
		name    string
		payload string
		want    []string
	}{
		{name: "soft", payload: `{"action":"soft_interrupt","message":"stop now"}`, want: []string{"runtime", "control", "soft_interrupt", "-s", "provider-secret", "-a", `{"message":"stop now"}`, "--json"}},
		{name: "hard", payload: `{"action":"hard_interrupt"}`, want: []string{"runtime", "control", "hard_interrupt", "-s", "provider-secret", "-a", `{}`, "--json"}},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
			a := newTestAdapter(t, runner)
			if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err != nil {
				t.Fatal(err)
			}
			runner.out = []byte(`{"delivery_boundary":"submitted"}`)
			_, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "interrupt-1", Operation: protocol.OperationExecutionInterrupt,
				Target:  &protocol.CommandTarget{ResourceID: "res_provider-secret", Generation: "g1"},
				Payload: []byte(testCase.payload),
			}})
			if err != nil {
				t.Fatalf("declared interrupt operation failed: %v", err)
			}
			if !reflect.DeepEqual(runner.args, testCase.want) {
				t.Fatalf("unexpected interrupt argv: %#v", runner.args)
			}
		})
	}
}

func TestTopsailaiAdapterRejectsInvalidInterruptPayload(t *testing.T) {
	for _, payload := range []string{
		`null`,
		`[]`,
		`{}`,
		`{"action":"interrupt"}`,
		`{"action":"clear_interrupt"}`,
		`{"action":"hard_interrupt","message":"not allowed"}`,
		`{"action":"soft_interrupt","unknown":true}`,
		`{"action":"soft_interrupt","message":1}`,
	} {
		t.Run(payload, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1"}]}`)}
			a := newTestAdapter(t, runner)
			if _, err := a.Discover(context.Background(), adapter.DiscoverRequest{}); err != nil {
				t.Fatal(err)
			}
			runner.args = nil
			_, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "interrupt-invalid", Operation: protocol.OperationExecutionInterrupt,
				Target:  &protocol.CommandTarget{ResourceID: "res_provider-secret", Generation: "g1"},
				Payload: []byte(payload),
			}})
			if err == nil || runner.args != nil {
				t.Fatalf("invalid payload reached provider: err=%v args=%#v", err, runner.args)
			}
		})
	}
}

func TestUnsupportedAndCloseDoNotOperateAgent(t *testing.T) {
	runner := &fakeRunner{}
	a := newTestAdapter(t, runner)
	if _, err := a.QueryCommand(context.Background(), adapter.CommandQuery{}); !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("query should be unsupported: %v", err)
	}
	if _, err := a.Watch(context.Background()); !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("watch should be unsupported: %v", err)
	}
	if err := a.Close(); err != nil || runner.args != nil {
		t.Fatalf("close operated on provider: %v %#v", err, runner.args)
	}
}

func TestReadOutputMarksProviderTruncation(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"s","process_generation":"g"}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	runner.out = []byte(`{"ok":true,"response":{"lines":["one"],"scan_limited":true}}`)
	output, err := a.ReadOutput(context.Background(), adapter.OutputRequest{Target: protocol.CommandTarget{ResourceID: result.Sessions[0].SessionID}, Limit: 10})
	if err != nil || !output.Truncated || !output.ScanLimited {
		t.Fatalf("truncation not reported: %#v %v", output, err)
	}
	if !reflect.DeepEqual(runner.args, []string{"runtime", "logs", "-s", "s", "-n", "10", "--json"}) {
		t.Fatalf("unexpected logs argv: %#v", runner.args)
	}
}

func contains(value, needle string) bool {
	for i := 0; i+len(needle) <= len(value); i++ {
		if value[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}

func TestStopUnsupportedWhenPlatformCapabilityMissing(t *testing.T) {
	runner := &fakeRunner{}
	a, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: false}, nil
	}}, runner)
	if err != nil {
		t.Fatal(err)
	}
	descriptor, err := a.Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	for _, capability := range descriptor.Capabilities.Capabilities {
		if capability.Name == "agent.stop" {
			t.Fatal("agent.stop must not be declared without pidfd support")
		}
	}
	result, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c1", Operation: "agent.stop", Target: &protocol.CommandTarget{ResourceID: "opaque", Generation: "g1"}}})
	if !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("stop error = %v, want ErrUnsupported", err)
	}
	if result.Receipt.CommandID != "" || runner.args != nil {
		t.Fatalf("unsupported stop performed work: %#v %#v", result, runner.args)
	}
}

func TestStopSupportedOnLinuxWithPidfd(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"signal_sent":true,"exit_confirmed":false}`)}
	a, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
	}}, runner)
	if err != nil {
		t.Fatal(err)
	}
	runner.out = []byte(`{"items":[{"session_id":"provider-key","process_generation":"g1"}]}`)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	_, err = a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c1", Operation: "agent.stop", Target: &protocol.CommandTarget{ResourceID: result.Sessions[0].SessionID, Generation: "g1"}}})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"workspace", "kill", "provider-key", "-g", "g1", "--json"}
	if !reflect.DeepEqual(runner.args, want) {
		t.Fatalf("argv = %#v, want %#v", runner.args, want)
	}
}

func TestDiscoverPopulatesFreshnessFields(t *testing.T) {
	a := newTestAdapter(t, &fakeRunner{out: []byte(`{"items":[]}`)})
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if !result.DataKnown || result.Stale || result.LastAttemptAtMS == 0 || result.LastSuccessAtMS == 0 || result.LastAttemptAtMS != result.LastSuccessAtMS {
		t.Fatalf("freshness = %#v", result)
	}
}

func TestInspectRejectsUnknownMappedResource(t *testing.T) {
	a := newTestAdapter(t, &fakeRunner{out: []byte(`{"items":[]}`)})
	result, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "unknown", Generation: "g1"}})
	if err == nil || result.Found {
		t.Fatalf("unknown resource result=%#v err=%v", result, err)
	}
}

func TestNewRejectsMissingIdentityAndInspectValidatesTarget(t *testing.T) {
	if _, err := New(Config{}); err == nil {
		t.Fatal("missing adapter configuration must fail")
	}
	a := newTestAdapter(t, &fakeRunner{})
	if _, err := a.Inspect(context.Background(), adapter.InspectRequest{}); err == nil {
		t.Fatal("missing inspect target must fail")
	}
	if _, err := a.Inspect(context.Background(), adapter.InspectRequest{Target: protocol.CommandTarget{ResourceID: "r", Generation: "g"}}); err == nil {
		t.Fatal("unknown mapping must fail")
	}
}

func TestReceiptFromJSONClassifiesFailuresAndUnknowns(t *testing.T) {
	intent := protocol.ImmutableIntent{CommandID: "c"}
	for _, tc := range []struct {
		name      string
		body      string
		certainty protocol.EffectCertainty
	}{
		{"failed", `{"delivery_state":"failed","error_code":"bad"}`, protocol.EffectNotApplied},
		{"unknown", `{"delivery_state":"unknown"}`, protocol.EffectUnknown},
		{"signal", `{"signal_sent":true}`, protocol.EffectAcknowledged},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := receiptFromJSON(intent, []byte(tc.body))
			if got.EffectCertainty != tc.certainty {
				t.Fatalf("receipt=%+v", got)
			}
		})
	}
}

func TestDiscoverPreservesProviderSessionNameWhileKeepingOpaqueID(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","session_name":"Daily work","process_generation":"g1","status":"running"}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Sessions) != 1 {
		t.Fatalf("sessions = %#v", result.Sessions)
	}
	session := result.Sessions[0]
	if session.DisplayName != "Daily work" {
		t.Fatalf("display name = %q, want Daily work", session.DisplayName)
	}
	if session.ProviderSessionID != "provider-secret" {
		t.Fatalf("provider session ID = %q, want provider-secret", session.ProviderSessionID)
	}
	if session.SessionID != "res_provider-secret" {
		t.Fatalf("session ID = %q, want opaque resource ID", session.SessionID)
	}
}

func TestDiscoverLeavesProviderSessionNameEmptyWhenAbsent(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-secret","process_generation":"g1","status":"running"}]}`)}
	a := newTestAdapter(t, runner)
	result, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if got := result.Sessions[0].DisplayName; got != "" {
		t.Fatalf("display name = %q, want empty", got)
	}
}

func TestTopsailaiAdapterStartCommandOptionalFolderAndNonInteractive(t *testing.T) {
	cases := []struct {
		name   string
		folder string
		want   []string
	}{
		{
			name: "without folder",
			want: []string{"workspace", "agent", "--background", "--json", "--non-interactive"},
		},
		{
			name:   "with folder containing spaces",
			folder: "/tmp/work folder --safe",
			want:   []string{"workspace", "agent", "/tmp/work folder --safe", "--background", "--json", "--non-interactive"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			runner := &fakeRunner{out: []byte(`{"status":"started"}`)}
			a := newTestAdapter(t, runner)
			_, err := a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID:       "start-1",
				Operation:       protocol.OperationAgentStart,
				LaunchProfileID: "profile",
				Folder:          tc.folder,
			}})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(runner.args, tc.want) {
				t.Fatalf("argv = %#v, want %#v", runner.args, tc.want)
			}
			for _, arg := range runner.args {
				if arg == "profile" || arg == "--folder" {
					t.Fatalf("argv contains forbidden provider argument %q: %#v", arg, runner.args)
				}
			}
		})
	}
}

// TestResumeUsesExplicitProviderSessionSelector pins the public provider CLI contract.
func TestResumeUsesExplicitProviderSessionSelector(t *testing.T) {
	runner := &fakeRunner{out: []byte(`{"items":[{"session_id":"provider-session","process_generation":"g1","status":"running"}]}`)}
	a := newTestAdapter(t, runner)
	discovered, err := a.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil || len(discovered.Sessions) != 1 {
		t.Fatalf("discover=%+v err=%v", discovered, err)
	}
	runner.out = []byte(`{"status":"submitted"}`)
	_, err = a.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "resume-contract", Operation: protocol.OperationAgentResume,
		Target: &protocol.CommandTarget{ResourceID: discovered.Sessions[0].SessionID, Generation: "g1"},
	}})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"workspace", "resume", "-s", "provider-session", "--background", "--json"}
	if !reflect.DeepEqual(runner.args, want) {
		t.Fatalf("argv=%q want=%q", runner.args, want)
	}
}
