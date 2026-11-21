package tui

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// detailStubAPI is a CommandAPI that also implements detailReader, so the info
// sections can be exercised without a real client.
type detailStubAPI struct {
	CommandAPI

	detail protocol.SessionDetail
	err    error
	calls  []string
}

// GetDetail records the queried session and returns the configured outcome.
func (s *detailStubAPI) GetDetail(_ context.Context, endpointID, sessionID string) (protocol.SessionDetail, error) {
	s.calls = append(s.calls, endpointID+"/"+sessionID)
	if s.err != nil {
		return protocol.SessionDetail{}, s.err
	}
	return s.detail, nil
}

// TestSessionDetailSectionsIsNilWithoutTheCapability proves a client that cannot
// read detail renders exactly what it rendered before, so a missing seam is
// invisible instead of being reported as a provider that returned nothing.
func TestSessionDetailSectionsIsNilWithoutTheCapability(t *testing.T) {
	read := readSessionDetail(context.Background(), nil, "endpoint-1", "provider-session-1")
	if read.Available {
		t.Fatalf("read without the capability reported Available, want false")
	}
	if got := sessionDetailSections(read); got != nil {
		t.Fatalf("sections without the capability=%v, want nil", got)
	}
}

// TestSessionDetailSectionsReportsMetadataAndRuntime proves both sections are
// produced, and that the runtime seam is reported as not reported rather than as
// an empty runtime. The two facts differ: the provider reported nothing, versus
// the cluster has no source for this field yet.
func TestSessionDetailSectionsReportsMetadataAndRuntime(t *testing.T) {
	api := &detailStubAPI{detail: protocol.SessionDetail{
		ProviderSessionID: "provider-session-1",
		ProviderMetadata:  `{"session_id":"provider-session-1","model":"m1"}`,
		ProviderRuntime:   "",
	}}
	sections := sessionDetailSections(readSessionDetail(context.Background(), api, "endpoint-1", "provider-session-1"))
	if len(sections) != 2 {
		t.Fatalf("sections=%d want 2: %+v", len(sections), sections)
	}
	if sections[0].label != "provider_metadata" || sections[1].label != "provider_runtime" {
		t.Fatalf("labels=%q,%q want provider_metadata,provider_runtime", sections[0].label, sections[1].label)
	}
	if !strings.Contains(sections[0].body, "model: m1") {
		t.Fatalf("metadata body is not readable text: %q", sections[0].body)
	}
	if sections[1].body != "not reported" {
		t.Fatalf("empty runtime body=%q want not reported", sections[1].body)
	}
}

// TestSessionDetailSectionsRendersANonEmptyRuntimeDocument proves the runtime
// seam is rendered when the provider actually reports one.
//
// Every other test in this package supplies an empty runtime, so before this one
// the renderer was only ever exercised on the "not reported" branch. A cluster
// that dropped the runtime document entirely would have passed the whole suite,
// because the only assertion about the seam was that it stays empty.
//
// The fixture is the envelope the provider publishes for one row, so the nesting
// depth is the provider's rather than one invented for the test. The assertions
// compare whole lines, because a substring match cannot distinguish a nested
// value from a top-level one: "  ok: true" is a substring of "    ok: true".
func TestSessionDetailSectionsRendersANonEmptyRuntimeDocument(t *testing.T) {
	const envelope = `{"state":"ok","error_code":"","pid":42,"data":{"ok":true,"agent2llm":{"messages":7},"user2agent":{"messages":3}}}`
	api := &detailStubAPI{detail: protocol.SessionDetail{
		ProviderMetadata: `{"session_id":"s1"}`,
		ProviderRuntime:  envelope,
	}}
	sections := sessionDetailSections(readSessionDetail(context.Background(), api, "endpoint-1", "s1"))
	if len(sections) != 2 {
		t.Fatalf("sections=%d want 2: %+v", len(sections), sections)
	}
	body := sections[1].body
	if body == "not reported" {
		t.Fatal("a reported runtime document was rendered as not reported, so the seam was dropped")
	}
	lines := make(map[string]bool)
	for _, line := range strings.Split(body, "\n") {
		lines[line] = true
	}
	// "messages" sits two levels below the document root, so it must carry two
	// indent levels. A renderer that flattened the nesting would still contain
	// the text, which is why the whole line is compared.
	for _, want := range []string{"data:", "  agent2llm:", "    messages: 7", "  ok: true", "  user2agent:", "    messages: 3", "pid: 42", "state: ok"} {
		if !lines[want] {
			t.Fatalf("runtime body has no line %q: %q", want, body)
		}
	}
}

// TestCommandRunnerInfoJSONModeCarriesANonEmptyRuntime proves a machine-readable
// caller receives the runtime document the text form renders.
//
// The envelope omits an empty seam through `omitempty`, so a caller cannot tell a
// dropped document from a provider that reported none. That is exactly the
// distinction the seam exists to preserve, so the non-empty case must survive the
// JSON path too.
func TestCommandRunnerInfoJSONModeCarriesANonEmptyRuntime(t *testing.T) {
	const envelope = `{"state":"ok","pid":42,"data":{"ok":true}}`
	api := detailRunnerFixture()
	api.detail.ProviderRuntime = envelope
	var out strings.Builder
	if err := (CommandRunner{API: api}).Info(context.Background(), &out, "res_1", true); err != nil {
		t.Fatalf("Info: %v", err)
	}
	var info SessionInfo
	if err := json.Unmarshal([]byte(out.String()), &info); err != nil {
		t.Fatalf("decode envelope: %v", err)
	}
	if info.ProviderRuntime != envelope {
		t.Fatalf("provider_runtime=%q, want the provider document verbatim", info.ProviderRuntime)
	}
}

// TestSessionDetailSectionsKeepsUnmodelledProviderFields proves the provider
// record is rendered whole. A curated subset would silently hide the field that
// answers the operator's question, and the cluster does not model the record so
// it cannot know which field that is.
func TestSessionDetailSectionsKeepsUnmodelledProviderFields(t *testing.T) {
	api := &detailStubAPI{detail: protocol.SessionDetail{
		ProviderMetadata: `{"session_id":"s1","unmodelled_field":"kept","nested":{"deep":"value"}}`,
	}}
	sections := sessionDetailSections(readSessionDetail(context.Background(), api, "endpoint-1", "s1"))
	if len(sections) == 0 {
		t.Fatal("no sections produced")
	}
	for _, want := range []string{"unmodelled_field: kept", "nested:", "deep: value"} {
		if !strings.Contains(sections[0].body, want) {
			t.Fatalf("metadata body missing %q: %q", want, sections[0].body)
		}
	}
}

// TestSessionDetailSectionsHasNoTruncationLabel proves the surface cannot present
// a shortened provider record as the complete record.
//
// The contract rejects an oversized document instead of shortening it, so there is
// no truncation flag to render. This test pins that absence: if a truncation label
// ever reappears, the contract has regressed to shortening documents silently.
func TestSessionDetailSectionsHasNoTruncationLabel(t *testing.T) {
	api := &detailStubAPI{detail: protocol.SessionDetail{
		ProviderMetadata: `{"session_id":"s1"}`,
	}}
	sections := sessionDetailSections(readSessionDetail(context.Background(), api, "endpoint-1", "s1"))
	for _, section := range sections {
		if strings.Contains(strings.ToLower(section.body), "truncated") {
			t.Fatalf("section %q carries a truncation label: %q", section.label, section.body)
		}
	}
}

// TestSessionDetailSectionsReportsFailures proves a failed read is visible. The
// operator asked for provider detail, so silence would be indistinguishable from
// a provider that has no detail to give.
func TestSessionDetailSectionsReportsFailures(t *testing.T) {
	for _, tc := range []struct {
		name string
		api  *detailStubAPI
		want string
	}{
		{
			name: "transport failure",
			api:  &detailStubAPI{err: errors.New("transport failure")},
			want: "read failed: transport failure",
		},
		{
			name: "provider error code",
			api:  &detailStubAPI{detail: protocol.SessionDetail{ErrorCode: protocol.DetailSessionNotFound}},
			want: "read failed: " + protocol.DetailSessionNotFound,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			sections := sessionDetailSections(readSessionDetail(context.Background(), tc.api, "endpoint-1", "s1"))
			if len(sections) != 1 {
				t.Fatalf("sections=%d want 1: %+v", len(sections), sections)
			}
			if sections[0].body != tc.want {
				t.Fatalf("body=%q want=%q", sections[0].body, tc.want)
			}
		})
	}
}

// TestSessionDetailSectionsRefusesAnUnaddressableSession proves a session with no
// provider identifier is reported rather than silently omitted, and that no
// provider call is made with an empty target.
func TestSessionDetailSectionsRefusesAnUnaddressableSession(t *testing.T) {
	api := &detailStubAPI{}
	sections := sessionDetailSections(readSessionDetail(context.Background(), api, "endpoint-1", ""))
	if len(api.calls) != 0 {
		t.Fatalf("provider was called with an empty target: %v", api.calls)
	}
	if len(sections) != 1 || !strings.Contains(sections[0].body, "not addressable") {
		t.Fatalf("sections=%+v want one not-addressable section", sections)
	}
}

// TestRenderSessionInfoAppendsProviderSections proves the sections reach the
// printed bytes after the standard fields, so the operator can tell where the
// provider document starts.
func TestRenderSessionInfoAppendsProviderSections(t *testing.T) {
	var out strings.Builder
	session := protocol.Session{ClusterSessionID: "res_1", ProviderSessionID: "provider-session-1", State: "running"}
	sections := []detailSection{
		{label: "metadata", body: "session_id: provider-session-1\nmodel: m1"},
		{label: "runtime", body: "not reported"},
	}
	if err := renderSessionInfoWithSections(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, session, sections); err != nil {
		t.Fatalf("renderSessionInfoWithSections: %v", err)
	}
	text := out.String()
	stateIndex := strings.Index(text, "state: running")
	metadataIndex := strings.Index(text, "metadata:")
	runtimeIndex := strings.Index(text, "runtime:")
	if stateIndex < 0 || metadataIndex < 0 || runtimeIndex < 0 {
		t.Fatalf("output missing a section: %q", text)
	}
	if !(stateIndex < metadataIndex && metadataIndex < runtimeIndex) {
		t.Fatalf("sections are not after the standard fields in order: %q", text)
	}
	if !strings.Contains(text, "  model: m1") {
		t.Fatalf("metadata body is not indented under its label: %q", text)
	}
}

// TestRenderSessionInfoWithoutSectionsIsUnchanged proves the plain renderer still
// produces no provider section, so a client without the capability sees exactly
// the previous output.
func TestRenderSessionInfoWithoutSectionsIsUnchanged(t *testing.T) {
	var out strings.Builder
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, protocol.Session{ClusterSessionID: "res_1"}); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	if strings.Contains(out.String(), "metadata:") || strings.Contains(out.String(), "runtime:") {
		t.Fatalf("plain renderer produced a provider section: %q", out.String())
	}
}

// TestDetailSectionsEscapeProviderText proves a provider document cannot inject
// terminal control sequences into the info output.
func TestDetailSectionsEscapeProviderText(t *testing.T) {
	var out strings.Builder
	sections := []detailSection{{label: "metadata", body: "session_id: \x1b[31mred"}}
	if err := writeDetailSections(&out, sections); err != nil {
		t.Fatalf("writeDetailSections: %v", err)
	}
	if strings.Contains(out.String(), "\x1b") {
		t.Fatalf("provider text kept a control sequence: %q", out.String())
	}
}

// detailRunnerStubAPI is a full CommandAPI that also reads detail, so the real
// Info entry point can be driven end to end instead of calling the helper alone.
type detailRunnerStubAPI struct {
	runnerStubAPI

	detail protocol.SessionDetail
	reads  []string
	// err makes the detail read fail, so the failure path can be exercised through
	// the real Info entry point rather than only through the helper.
	err error
}

// GetDetail records the read so a test can prove whether the entry point asked
// the provider at all.
func (s *detailRunnerStubAPI) GetDetail(_ context.Context, endpointID, sessionID string) (protocol.SessionDetail, error) {
	s.reads = append(s.reads, endpointID+"/"+sessionID)
	if s.err != nil {
		return protocol.SessionDetail{}, s.err
	}
	return s.detail, nil
}

// detailRunnerFixture builds one endpoint reporting one session, so Info can
// resolve the identifier through the real inventory path.
func detailRunnerFixture() *detailRunnerStubAPI {
	return &detailRunnerStubAPI{
		runnerStubAPI: runnerStubAPI{
			endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
			reports: map[string]protocol.InventoryReport{
				"ep-1": {CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{
					ClusterSessionID:  "res_1",
					ProviderSessionID: "provider-session-1",
					State:             "running",
				}}},
			},
		},
		detail: protocol.SessionDetail{
			ProviderSessionID: "provider-session-1",
			ProviderMetadata:  `{"session_id":"provider-session-1","unmodelled_field":"kept"}`,
		},
	}
}

// TestCommandRunnerInfoRendersProviderSections proves the composed path works:
// the real Info entry point reads the provider document and prints it. A helper
// test alone would pass even if no caller ever invoked the helper, which is the
// failure this test exists to catch.
func TestCommandRunnerInfoRendersProviderSections(t *testing.T) {
	api := detailRunnerFixture()
	var out strings.Builder
	if err := (CommandRunner{API: api}).Info(context.Background(), &out, "res_1", false); err != nil {
		t.Fatalf("Info: %v", err)
	}
	text := out.String()
	if len(api.reads) != 1 || api.reads[0] != "ep-1/provider-session-1" {
		t.Fatalf("reads=%v want one read of ep-1/provider-session-1", api.reads)
	}
	for _, want := range []string{"metadata:", "unmodelled_field: kept", "runtime:", "not reported"} {
		if !strings.Contains(text, want) {
			t.Fatalf("info output missing %q: %q", want, text)
		}
	}
}

// TestCommandRunnerInfoJSONModeCarriesTheProviderSeams proves a machine-readable
// caller sees the same provider documents the text form shows.
//
// The seams exist so an operator can read a provider's own record. A script is an
// operator too, so omitting them from the envelope would make the seam visible only
// to a human reading a terminal, and a caller could not answer the same question
// the text form answers.
func TestCommandRunnerInfoJSONModeCarriesTheProviderSeams(t *testing.T) {
	api := detailRunnerFixture()
	var out strings.Builder
	if err := (CommandRunner{API: api}).Info(context.Background(), &out, "res_1", true); err != nil {
		t.Fatalf("Info: %v", err)
	}
	if len(api.reads) == 0 {
		t.Fatal("json mode did not read the provider, so the seams are missing")
	}
	var info SessionInfo
	if err := json.Unmarshal([]byte(out.String()), &info); err != nil {
		t.Fatalf("decode envelope: %v", err)
	}
	if !strings.Contains(info.ProviderMetadata, "unmodelled_field") {
		t.Fatalf("provider_metadata=%q, want the provider record verbatim", info.ProviderMetadata)
	}
	if info.ProviderRuntime != "" {
		t.Fatalf("provider_runtime=%q, want empty because the provider reported none", info.ProviderRuntime)
	}
	if info.ProviderDetailError != "" {
		t.Fatalf("provider_detail_error=%q, want empty on a successful read", info.ProviderDetailError)
	}
}

// TestCommandRunnerInfoJSONModeReportsAReadFailure proves a failed read is visible
// to a machine-readable caller instead of looking like a provider that reported
// nothing. The two facts need different handling, so they must not share one
// representation.
func TestCommandRunnerInfoJSONModeReportsAReadFailure(t *testing.T) {
	api := detailRunnerFixture()
	api.err = errors.New("transport failure")
	var out strings.Builder
	if err := (CommandRunner{API: api}).Info(context.Background(), &out, "res_1", true); err != nil {
		t.Fatalf("Info: %v", err)
	}
	var info SessionInfo
	if err := json.Unmarshal([]byte(out.String()), &info); err != nil {
		t.Fatalf("decode envelope: %v", err)
	}
	if !strings.Contains(info.ProviderDetailError, "transport failure") {
		t.Fatalf("provider_detail_error=%q, want the read failure", info.ProviderDetailError)
	}
	if info.ProviderMetadata != "" || info.ProviderRuntime != "" {
		t.Fatalf("a failed read carried documents: %+v", info)
	}
}

// TestCommandRunnerInfoWithoutTheCapabilityStillRenders proves a client that
// cannot read detail keeps the previous output instead of failing the command.
func TestCommandRunnerInfoWithoutTheCapabilityStillRenders(t *testing.T) {
	api := detailRunnerFixture()
	var out strings.Builder
	plain := CommandRunner{API: &api.runnerStubAPI}
	if err := plain.Info(context.Background(), &out, "res_1", false); err != nil {
		t.Fatalf("Info: %v", err)
	}
	text := out.String()
	if !strings.Contains(text, "state: running") {
		t.Fatalf("standard fields are missing: %q", text)
	}
	if strings.Contains(text, "metadata:") || strings.Contains(text, "runtime:") {
		t.Fatalf("a client without the capability produced a provider section: %q", text)
	}
}
